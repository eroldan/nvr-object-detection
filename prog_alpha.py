import sys, os, time, queue, threading, io, traceback
from requests.auth import HTTPBasicAuth
import requests, logging
import darknet
import PIL, PIL.Image, PIL.ImageDraw, PIL.ImageFont
import yaml
import collision


INTERESTING_OBJECTS = ('person')
#INTERESTING_OBJECTS = ('person', 'dog', 'cat')
DETECTION_THRESHOLD = 0.9
FRAME_QUEUE_SIZE = 2
FRAME_THREAD_COUNT = 2
TMPDPATH = './corpus/'
DETECTEDPATH = './detected'
DETECT_THREADCOUNT= 1
DETECT_IMG_FORMAT = 'jpg'
STATUS_PERIOD_TIME = 1
FONT_NAME='consolab.ttf'
FONT_SIZE=25
RECTANGLE_WIDTH=4
CAMERA_CONFIG = 'camera-config.yaml'

class Camera:
    def __init__(self, cconfig):
        self.cconfig = cconfig
        if 'hikvision' in cconfig['schema']:
            self.get_img = self.hikvision_get_img

    def get_img(self):
        print('No know camera schema')
        sys.exit(1)

    def hikvision_get_img(self):
        address = self.cconfig['address']
        resize = [ int(x) for x in self.cconfig['resize'].split(',') ]
        channel = self.cconfig['schema']['hikvision']['channel']
        digest_auth = self.cconfig['schema']['hikvision']['digest-auth']
        fname = os.path.join(TMPDPATH, "{}-{}.jpg".format(channel, str(time.time())))
        url = 'http://{}/ISAPI/Streaming/channels/{}/picture'.format(address, channel)
        print("pull {}".format(url))
        img = PIL.Image.open(io.BytesIO(requests.get(url=url, timeout=5, auth=HTTPBasicAuth(*digest_auth.split(':'))).content))
        img.thumbnail(resize, resample=PIL.Image.NEAREST)
        img.save(fname)
        return fname, img
        

class pull_nvr_thread(threading.Thread):
    def __init__(self, camera_iter, *args, **kwargs):
        self.cameras = camera_iter
        super().__init__(*args, **kwargs)
    
    def run(self):
        print("Thread {} starting".format(self.name))
        lastfail = 0
        for camera in self.cameras:
            if stop:
                break
            try:
                fname, img = camera.get_img()
                try:
                    nvr_queue.put((fname, img, camera), timeout=5)
                except queue.Full:
                    if not stop: print("discarding frame, too old {}".format(fname))
                    os.unlink(os.path.join(fname))
                    continue
            except Exception:
                print("-"*60)
                traceback.print_exc(file=sys.stdout)
                print("-"*60)
                if time.time() > lastfail + 5:
                    print('Too many pull fails, sleeping')
                    time.sleep(5)
                    lastfail = time.time()
        print("thread {} stoping".format(self.name))

            
class detect_thread(threading.Thread):
    def run(self):
        print("Thread {} starting".format(self.name))
        global global_detections_counter, stop
        v = collision.Vector

        while not stop:
            try:
                fname, img, camera = nvr_queue.get(timeout=1)
            except queue.Empty:
                print("Image buffer is empty, !")
                continue
                
            nvr_queue.task_done()         
            detected = darknet.performDetect(imagePath=fname, showImage=False, thresh=DETECTION_THRESHOLD)
            os.unlink(fname)
            global_detections_counter += 1 
            detected = [x for x in detected if x[0] in INTERESTING_OBJECTS]
            #font = PIL.ImageFont.truetype(FONT_NAME, FONT_SIZE)
            #detected = [('Fake', 1, (100, 100, 50, 50))]
            if detected:
                print(detected)
                draw = PIL.ImageDraw.Draw(img)

                for a in camera.cconfig['areas']:
                    apolys = [ (int(x), int(y)) for (x, y) in [ line.split(',') for line in a['poly-points'] ]]
                    draw.polygon( apolys, outline='LawnGreen')
                    for obj, confidence, (center_x, center_y, width, height) in detected:
                        dcolor = 'yellow'
                        darea = collision.Concave_Poly(v(0,0), [ v(x, y) for (x, y) in apolys ])
                        dobj = collision.Concave_Poly(v(0,0), [ v(center_x - width/2, center_y - height/2),
                                                                v(center_x - width/2, center_y + height/2),
                                                                v(center_x + width/2, center_y + height/2),
                                                                v(center_x + width/2, center_y - height/2)
                                                              ]
                                                    )
                        if collision.collide(dobj, darea):
                            dcolor = 'fuchsia'
                        draw.rectangle(xy=(center_x - width/2, center_y - height/2,
                                           center_x + width/2, center_y + height/2),
                                    outline=dcolor,
                                    width=RECTANGLE_WIDTH
                                    )
            #       draw.text(xy=((center_x - width/2), (center_y - height/2) - FONT_SIZE),
            #                     text="{}({})".format(obj, int(confidence * 100)),
            #                     fill='fuchsia',
            #                     font=font,
            #                     stroke_fill='pink',
            #                     stroke_width=1
            #                     )
                img.save(os.path.join(DETECTEDPATH, '{}.{}'.format(time.time(), DETECT_IMG_FORMAT)))
        print("Thread {} stoping".format(self.name))

            
class camera_iterator():
    def __init__(self, cconfigs):
        cconfigs=list(cconfigs)
        self.list = []
        self.max = len(cconfigs) -1
        self.pos = -1
        self.lock = threading.Lock()

        for cconfig in cconfigs:
            if cconfig['kind'] == 'Camera':
                self.list.append(Camera(cconfig))
            else:
                print('Unknown object definition')
                sys.exit(1)
        
    def __iter__(self):
        return self
        
    def __next__(self):
        self.lock.acquire()
        self.pos = self.pos + 1 if self.pos < self.max else 0
        camera = self.list[self.pos]
        self.lock.release()
        return camera    

        
def cleanup():
    for f in os.listdir(TMPDPATH): os.unlink(os.path.join(TMPDPATH, f))
    
    
def main():
    #logging.basicConfig(level=logging.DEBUG)

    cleanup()
    
    global global_detections_counter, stop
    camera_iter = camera_iterator(yaml.safe_load_all(open('./camera-config.yaml')))

    darknet.performDetect(imagePath="./none.jpg", showImage=False, thresh=0.5)
        
    nvr_threadlist = []
    for t in range(FRAME_THREAD_COUNT):
       nvr_threadlist.append(pull_nvr_thread(camera_iter, name='pull_nvr-{}'.format(t)))
       nvr_threadlist[t].start()
      
        
    detect_threadlist = []
    for t in range(DETECT_THREADCOUNT):
       detect_threadlist.append(detect_thread(name='detect-{}'.format(t)))
       detect_threadlist[t].start()

    try:
        while True:
            time.sleep(STATUS_PERIOD_TIME)
            print("FPS: {}, QSIZE: {}".format(global_detections_counter/STATUS_PERIOD_TIME, nvr_queue.qsize()))
            global_detections_counter = 0
    except KeyboardInterrupt as e:
        stop = True


global_detections_counter = 0
stop = False
nvr_queue = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
detected_queue = queue.Queue()
if __name__ == "__main__":
    main()

