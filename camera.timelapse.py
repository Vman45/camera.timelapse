from picamera import PiCamera
from PIL import Image
import argparse
import datetime
import glob
import fractions
import keyboard
import numpy
import os
import statistics
import subprocess
import sys
import threading
import time

version = '2020.09.12'

camera = PiCamera()
#camera.resolution = camera.MAX_RESOLUTION
camera.resolution = (1920, 1080)
camera.sensor_mode = 3
camera.framerate = 1


# === Argument Handling ========================================================

parser = argparse.ArgumentParser()
parser.add_argument('--interval', dest='interval', help='Set the timelapse interval')
parser.add_argument('--framerate', dest='framerate', help='Set the output framerate')
parser.add_argument('--outputFolder', dest='outputFolder', help='Set the folder where images will be saved')
parser.add_argument('--retention', dest='retention', help='Set the number of days to locally retain the captured files')
parser.add_argument('--renderVideo', dest='renderVideo', help='Set whether a video is generated every 24 hours')
parser.add_argument('--uploadVideo', dest='uploadVideo', help='Set whether to automatically upload videos to YouTube')
parser.add_argument('--privacy', dest='privacy', help='Set the privacy status of the YouTube video')

args = parser.parse_args()

interval = args.interval or 10
try:
	interval = int(interval)
except:
	interval = 10

framerate = args.framerate or 60
try:
	framerate = int(framerate)
except:
	framerate = 60
shutter = int((1/(int(framerate)*2)) * 10000000)
defaultFramerate = 30



retention = args.retention or 7
try: 
	retention = int(retention)
except:
	retention = 7


renderVideo = args.renderVideo or True
if renderVideo != False:
	renderVideo = True
renderingInProgress = False


uploadVideo = args.uploadVideo or False
if renderVideo != True:
	renderVideo = False

outputFolder = args.outputFolder or 'dcim/'
if outputFolder.endswith('/') == False:
	outputFolder = outputFolder+'/'

privacy = args.privacy or 'public'

brightnessThreshold = 35

# === Echo Control =============================================================

def echoOff():
	subprocess.run(['stty', '-echo'], check=True)
def echoOn():
	subprocess.run(['stty', 'echo'], check=True)
def clear():
	subprocess.call('clear' if os.name == 'posix' else 'cls')
clear()


# === Functions ================================================================

def getFileName(imageCounter = 1):
	now = datetime.datetime.now()
	datestamp = now.strftime('%Y%m%d')
	extension = '.jpg'
	return datestamp + '-' + str(imageCounter).zfill(8) + extension


# ------------------------------------------------------------------------------

def getFilePath(imageCounter = 1):
	try:
		os.makedirs(outputFolder, exist_ok = True)
	except OSError:
		print ('\n ERROR: Creation of the output folder ' + outputFolder + ' failed!' )
		echoOn()
		quit()
	else:
		return outputFolder + getFileName(imageCounter)

# ------------------------------------------------------------------------------

def captureTimelapse():
	try:
		global interval
		global outputFolder
		started = datetime.datetime.now().strftime('%Y%m%d')

		if started != datetime.datetime.now().strftime('%Y%m%d'):
			# It is a new day, reset the counter
			started = datetime.datetime.now().strftime('%Y%m%d')
			counter = 1
		else:		
			# Set counter start based on last image taken today (allows multiple distinct sequences to be taken in one day)
			latestImagePath = max(glob.iglob(outputFolder + started + '-*.jpg'),key=os.path.getmtime)
			try:
				counter = int(latestImagePath.replace(outputFolder + started + '-', '').replace('.jpg', '')) + 1
			except:
				counter = 1
				pass
		
		print(' INFO: Starting timelapse sequence at an interval of ' + str(interval) + ' seconds...')		
		while True:
			camera.capture(getFilePath(counter))
			counter += 1					
			time.sleep(interval)
	except Exception as ex: 
		print(' WARNING: Could not capture most recent image. ' + str(ex))
		


# ------------------------------------------------------------------------------

def analyzeLastImages():
	global interval
	global framerate 

	try:
		time.sleep(interval * 1.5) 
		measuredBrightnessList = []
			
		while True:	
			latestImagePath = max(glob.iglob(outputFolder + '*.jpg'),key=os.path.getmtime)
			try:			
				latestImage = Image.open(latestImagePath)
				measuredBrightness = numpy.mean(latestImage)
				measuredBrightnessList.append(float(measuredBrightness))

				if len(measuredBrightnessList) >= (framerate * 0.25):
					measuredAverageBrightness = statistics.mean(measuredBrightnessList)
					print(' INFO: Average brightness of ' + str((framerate * 0.25)) + ' recent images: ' + str(measuredAverageBrightness))
					if measuredAverageBrightness < (brightnessThreshold - 10) and measuredAverageBrightness > -1:
						if camera.framerate >= 30:
							print(' INFO: Entering long exposure mode based on analysis of last image set... ')
							slowFramerate = fractions.Fraction(1, 10)							
							try:							
								camera.framerate = slowFramerate
							except Exception as ex:
								print('Error setting framerate to ' + str(slowFramerate) + ' ' + str(ex))
								pass						
					elif measuredAverageBrightness > (brightnessThreshold + 10):
						if camera.framerate < 30:
							print(' INFO: Exiting long exposure mode based on analysis of last image set...  ')
							camera.framerate = 30
					
					measuredBrightnessList.clear()

			except:
				# Ignore errors as sometimes a file will still be in use and can't be analyzed
				pass
			time.sleep(interval)
	except Exception:
		print(' WARNING: Could not analyze most recent image. ')

# ------------------------------------------------------------------------------

def convertSequenceToVideo(dateToConvert):
	try:
		global framerate
		global renderingInProgress
		global outputFolder		
		renderingInProgress = True
		dateToConvertStamp = dateToConvert.strftime('%Y%m%d')		
		outputFilePath = dateToConvertStamp + '.mp4'	
		print('\n INFO: Converting existing image sequence to video... ')
		# The following runs out of memory as it is not hardware accelerated, perhaps in the future?
		# subprocess.call('cd ' + outputFolder +  '&& ffmpeg -y -r 60 -i '+dateToConvertStamp+'-%08d.jpg -s hd1080 -vcodec libx265 -crf 20 -preset slow '+ outputFilePath, shell=True)
		# The following is not as an efficient codec, but encoding is hardware accelerated and should work for the transient purposes it is used for.
		subprocess.call('cd ' + outputFolder +  '&& ffmpeg -y -r 60 -i '+dateToConvertStamp+'-%08d.jpg -s hd1080 -qscale:v 3 -vcodec mpeg4 '+ outputFilePath, shell=True)
		renderingInProgress = False
		if uploadVideo: 
			try:		
				print('\n INFO: Uploading video... ')	
				uploadDescription = 'Timelapse for ' + dateToConvert.strftime('%Y-%m-%d')
				subprocess.call('python3 camera.timelapse/camera.timelapse.upload.py --file ' + outputFolder + outputFilePath + ' --title '' + dateToConvertStamp + '' --description '' + uploadDescription + '' --privacyStatus ' + privacy + ' --noauth_local_webserver ' , shell=True)
			except Exception as ex:
				print(' WARNING: YouTube upload may have failed! ' + str(ex) ) 	
	except ffmpeg.Error as ex:
		print(' ERROR: Could not convert sequence to video. ')

# ------------------------------------------------------------------------------

def cleanup():
	try:
		global outputFolder
		global retention
		now = time.time()
		print('\n INFO: Starting removal of files older than ' + str(retention) + ' days... ')
		for file in os.listdir(outputFolder):
			filePath = os.path.join(outputFolder, file)
			fileModified = os.stat(filePath).st_mtime
			fileCompare = now - (retention * 86400)
			if fileModified < fileCompare:
				os.remove(filePath)
		print(' INFO: Cleanup complete')
	except Exception as ex:
		print('\n ERROR: ' + str(ex) )


# === Timelapse Capture ========================================================

try: 
	os.chdir('/home/pi') 

	print('\n Camera (Timelapse) ' + version )
	print('\n ----------------------------------------------------------------------\n')
		
	#print(camera.shutter_speed)		
	while True:
		if keyboard.is_pressed('ctrl+c') or keyboard.is_pressed('esc'):
			# clear()
			echoOn()
			break
		
		camera.start_preview(fullscreen=False, resolution=(1920, 1080), window=(60, 60, 640, 360))				
		time.sleep(3)	
		camera.framerate = defaultFramerate
		camera.shutter_speed = shutter
		
		#print(' Shutter Speed: ' + str(camera.exposure_speed)) 
		# camera.iso = 400
		#print(' ISO: ' + str(camera.iso))
		captureThread = threading.Thread(target=captureTimelapse)
		captureThread.start()

		analysisThread = threading.Thread(target=analyzeLastImages)
		analysisThread.start()

		if retention > 0:
			cleanupThread = threading.Thread(target=cleanup)
			cleanupThread.start()
		else:
			print('\n WARNING: Retaining captured files indefinitely ')
			print('          Please ensure that sufficient storage exists or set a retention value ')

		while renderVideo:			
			if renderingInProgress == False:
				time.sleep(interval)
				yesterday = (datetime.date.today() - datetime.timedelta(days = 1))
				yesterdayStamp = yesterday.strftime('%Y%m%d')
				firstFrameExists = os.path.exists(outputFolder + yesterdayStamp + '-00000001.jpg')
				videoExists = os.path.exists(outputFolder + yesterdayStamp + '.mp4')
				if firstFrameExists == True and videoExists == False:
					convertThread = threading.Thread(target=convertSequenceToVideo, args=(yesterday,))
					convertThread.start()
					#convertSequenceToVideo(yesterday)
			time.sleep(3600)


except KeyboardInterrupt:
	camera.close()
	echoOn()
	sys.exit(1)

else:
	echoOn()
	sys.exit(0)
