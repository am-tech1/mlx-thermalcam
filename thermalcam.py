#***
# Thermal Camera - using RasPi, NoIR camera, and MLX90640
# works with 7 inch touch screen at video mode 36 - 720x480
#
# raspberry pi needs to have camera and i2c enabled, set i2c baudrate as fast as possible in config,txt: dtparam=i2c1_baudrate=1000000
# 
# requires opencv, numpy, matplotlib, imutils and bsdz mlx90640-library - https://github.com/bsdz/mlx90640-library
#
# controls:
# NV - plain video, add an IR illuminator to have "night vision".
# TV - plain thermal mode. press button again to cycle through colourmaps.
# HV - hybrid vision mode, thermal overlaid over video. press button again to cycle through colourmaps.
# ! - take a snapshot
# LK - lock thermal frame to video frame. this slows down video FPS to the same rate as thermal, but prevents the thermal from lagging behind video.
# X - exit 
#*** 

import os
import sys
import time
from time import sleep

import threading
from threading import Thread, Event
from queue import Queue

import numpy as np
import cv2

import matplotlib as mpl
from matplotlib import cm

import imutils
from imutils.video import VideoStream

from MLX90640 import API, ffi, temperature_data_to_ndarray, hertz_to_refresh_rate

import tkinter
from tkinter import *
from PIL import Image
from PIL import ImageTk

RESOLUTION = [320,240] #this is the thermal upscale resolution, would not recommend to go higher
FULLRESOLUTION = [720,480] #output display resolution

centrexy=[int(FULLRESOLUTION[0]/2),int(FULLRESOLUTION[1]/2)]

class ThermalApp():
    def __init__(self):
        self.THERMALON = True
        self.VIDEOON = True
        self.tempmid = ""
        self.tempmin = ""
        self.tempmax = ""
        self.fps = ""
        self.usequeue = True #this keeps the thermal overlay locked to the camera feed, restricting camera fps so the thermal doesn't lag behind
        self.tframe = Queue()
        self.colormaps = ['jet_r','gray_r','seismic_r','Greys_r'] #can have more colourmaps here, see matplotlib docs
        self.currentcm = 0
        self.cmap = cm.get_cmap(self.colormaps[self.currentcm])

        self.threadthermal = Thread(target=self.thermalworker, args=()) #starting thermal thread
        self.threadthermal.daemon = True
        self.threadthermal.start()
    
    def cm_up(self): # cycle colourmap up
        if self.currentcm < (len(self.colormaps)-1):
            self.currentcm += 1
        elif self.currentcm == (len(self.colormaps)-1):
            self.currentcm = 0

        self.cmap = cm.get_cmap(self.colormaps[self.currentcm])

    def cm_down(self): #cycle colourmap down
        if self.currentcm > 0:
            self.currentcm -= 1
        elif self.currentcm == 0:
            self.currentcm == (len(self.colormaps)-1)
        self.cmap = cm.get_cmap(self.colormaps[self.currentcm])

    def td_to_image(self, f, cmap):
        self.f = f
        norm = mpl.colors.Normalize(vmin=self.f.min(),vmax=self.f.max()) ## original implementation
        self.tempmin = self.f.min()
        self.tempmax = self.f.max()
        heattemp = np.uint8(self.cmap(norm(self.f))*255)        
        heattemp = cv2.flip( heattemp, 1 )
        heattemp = cv2.cvtColor(heattemp, cv2.COLOR_BGR2RGB)
      
        return heattemp

    def thermalworker(self):
        # mlx90640 settings
        self.MLX_I2C_ADDR = 0x33
        self.hertz_default = 8
        API.SetRefreshRate(self.MLX_I2C_ADDR, hertz_to_refresh_rate[self.hertz_default])
        API.SetChessMode(self.MLX_I2C_ADDR)

        # Extract calibration data from EEPROM and store in RAM
        self.eeprom_data = ffi.new("uint16_t[832]")
        self.params = ffi.new("paramsMLX90640*")
        API.DumpEE(self.MLX_I2C_ADDR, self.eeprom_data)
        API.ExtractParameters(self.eeprom_data, self.params)

        self.TA_SHIFT = 8 # the default shift for a MLX90640 device in open air
        self.emissivity = 0.95

        self.frame_buffer = ffi.new("uint16_t[834]")
        self.image_buffer = ffi.new("float[768]")
        print ("Starting thermal worker")
        while True:
            t1 = time.perf_counter()
            API.GetFrameData(self.MLX_I2C_ADDR, self.frame_buffer);
            # get reflected temperature based on the sensor
            # ambient temperature
            tr = API.GetTa(self.frame_buffer, self.params) - self.TA_SHIFT
            # The object temperatures for all 768 pixels in a
            # frame are stored in the mlx90640To array
            API.CalculateTo(self.frame_buffer, self.params, self.emissivity, tr, self.image_buffer);

            ta_np = temperature_data_to_ndarray(self.image_buffer)
            self.tempmid = ta_np[12,16]
            self.heatmap = self.td_to_image(ta_np, self.cmap)
            if self.usequeue:
                while not self.tframe.empty():
                    self.tframe.get()
                self.tframe.put(self.heatmap)            
            t2 = time.perf_counter()
            time1 = (t2-t1)
         
            self.fps = " {:.1f} FPS".format(1/time1)

class SensorApp(tkinter.Tk):
    def __init__(self):
        tkinter.Tk.__init__(self)
        self.attributes('-fullscreen', True)
        self.geometry('%dx%d+%d+%d' % (FULLRESOLUTION[0],FULLRESOLUTION[1],0,0))
        self.lastimg = None
        self.lastframe = None #last combined frame

        #starting thermal, needs to sleep for a sec to catch up
        self.thermalrunner = ThermalApp()
        sleep(1)
        #thermal started

        container = Frame(self)
        container.pack(side="top", fill="both", expand=True)

        self.pages = {} #will expand this to add a gallery page to see snapshots
        frame = ViewPage(container, self)
        self.pages[ViewPage] = frame
        frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame(ViewPage) #start thermal viewer page

    def show_frame(self,cont):
        frame = self.pages[cont]
        frame.tkraise()


    def killapp(self):
        print("going down")
        self.destroy()

class ViewPage(Frame):
    def __init__(self, parent, controller): 
        Frame.__init__(self,parent)
        self.fps = ""

        self.controller = controller
        self.videocanvas = Canvas(self, width = FULLRESOLUTION[0], height = FULLRESOLUTION[1], bg= "white")
        self.videocanvas.pack(side="top", fill="both", expand=True)

        self.vidimg = self.videocanvas.create_image(0, 0, anchor = tkinter.NW) #image on canvas obj for displaying video
        self.cantemp = self.videocanvas.create_text((centrexy[0]+10),centrexy[1], text="{0:.1f}".format(self.controller.thermalrunner.tempmid), fill='white', font=("System", 14), anchor = tkinter.NW)
        self.cantempmax = self.videocanvas.create_text(((FULLRESOLUTION[0]/2)-65),(FULLRESOLUTION[1]-50), text="Max Temp: {0:.1f}".format(self.controller.thermalrunner.tempmax), fill='white', font=("System", 14), anchor = tkinter.NW)
        self.cantempmin = self.videocanvas.create_text(((FULLRESOLUTION[0]/2)-65),(FULLRESOLUTION[1]-25), text="Min Temp: {0:.1f}".format(self.controller.thermalrunner.tempmin), fill='white', font=("System", 14), anchor = tkinter.NW)
        self.canthermfps = self.videocanvas.create_text((FULLRESOLUTION[0]-100),25, text=self.controller.thermalrunner.fps, font=("System", 14), fill='red', anchor = tkinter.NW)                
        self.canfps = self.videocanvas.create_text((FULLRESOLUTION[0]-100),5, text=self.fps, font=('System', 14), fill='white', anchor = tkinter.NW)                
        self.centre = self.videocanvas.create_oval((centrexy[0]-3),(centrexy[1]-3),(centrexy[0]+3),(centrexy[1]+3), fill='red')

        self.video_frame()
        self.closeBtn = Button(self, text="X", width=2, height=2, command=self.controller.killapp).place(x=5, y=(FULLRESOLUTION[1]-55))
        self.camBtn = Button(self, text="NV", width=2, height=2, command=self.keycallback).place(x=5, y=5)
        self.thermBtn = Button(self, text="TV", width=2, height=2, command=self.keycalltherm).place(x=5, y=60)
        self.hybBtn = Button(self, text="HV", width=2, height=2, command=self.keycallhyb).place(x=5, y=115)
        self.lockBtn = Button(self, text="Lk", width=2, height=2, command=self.lockframe).place(x=5, y=(FULLRESOLUTION[1]-105))
        self.snapBtn = Button(self, text="!", width=2, height=2, command=self.snapshot).place(x=(FULLRESOLUTION[0]-50), y=(FULLRESOLUTION[1]-55))


    def video_frame(self):
        t1 = time.perf_counter()

        if self.controller.thermalrunner.THERMALON:
            if self.controller.thermalrunner.VIDEOON:
                frame = vs.read()
                if self.controller.thermalrunner.usequeue:
                    heatframe = self.controller.thermalrunner.tframe.get() #locks video frame to thermal, lower fps but no lag between thermal and video
                else:
                    heatframe = self.controller.thermalrunner.heatmap
                heatframe = cv2.resize(heatframe,(int(RESOLUTION[0]),int(RESOLUTION[1])))
                frame = cv2.addWeighted(frame,0.4,heatframe,0.5,0)
            else:
                heatframe = self.controller.thermalrunner.heatmap
                frame = cv2.resize(heatframe,(int(RESOLUTION[0]),int(RESOLUTION[1])))

        else:
            frame = vs.read()
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        self.controller.lastimg = frame
        img = Image.fromarray(frame)
        img = img.resize((FULLRESOLUTION[0],FULLRESOLUTION[1]))

        imgtk = ImageTk.PhotoImage(image = img)
        self.controller.lastframe = imgtk
        self.videocanvas.imgtk = imgtk
        self.videocanvas.itemconfig(self.vidimg, image=self.videocanvas.imgtk)
        
        #if thermal draw target temperature on canvas and show thermal fps
        if self.controller.thermalrunner.THERMALON:
            self.videocanvas.itemconfig(self.cantemp, text="{0:.1f}".format(self.controller.thermalrunner.tempmid))
            self.videocanvas.itemconfig(self.cantempmax, text="Max Temp: {0:.1f}".format(self.controller.thermalrunner.tempmax))
            self.videocanvas.itemconfig(self.cantempmin, text="Min Temp: {0:.1f}".format(self.controller.thermalrunner.tempmin))
            self.videocanvas.itemconfig(self.canthermfps, text=self.controller.thermalrunner.fps)
        
        #draws fps on canvas if video feed is on.
        if self.controller.thermalrunner.VIDEOON:
            self.videocanvas.itemconfig(self.canfps, text=self.fps)

        t2 = time.perf_counter()
        time1 = (t2-t1)
        self.fps = " {:.1f} FPS".format(1/time1)

        self.videocanvas.after(10, self.video_frame)

    def snapshot(self):
        frame = cv2.resize(self.controller.lastimg,(int(FULLRESOLUTION[0]),int(FULLRESOLUTION[1])))
        cv2.imwrite("frame-" + time.strftime("%d-%m-%Y-%H-%M-%S") + ".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    def lockframe(self): # lock video frame to thermal frame, this switches the thermal thread to using queues which syncs up video to thermal
        print("locking frames")
        if self.controller.thermalrunner.usequeue:
            self.controller.thermalrunner.usequeue = False
        else:
            self.controller.thermalrunner.usequeue = True    

    def keycalltherm(self): #switch to plain thermal
        print("keycalltherm")
        if (self.controller.thermalrunner.VIDEOON == False) and (self.controller.thermalrunner.THERMALON == True):
            print("thermal vision - cm up") #cm down will be set up as another button later, for now just cycle through colourmaps using cm_up
            self.controller.thermalrunner.cm_up()

        self.controller.thermalrunner.VIDEOON = False
        self.controller.thermalrunner.THERMALON = True
        self.videocanvas.itemconfigure(self.cantempmax, state='normal')
        self.videocanvas.itemconfigure(self.cantempmin, state='normal')
        self.videocanvas.itemconfigure(self.cantemp, state='normal')
        self.videocanvas.itemconfigure(self.canthermfps, state='normal')
        self.videocanvas.itemconfigure(self.canfps, state='hidden')
 
    def keycallhyb(self): #switch to hybrid mode where thermal is overlaid over video
        print("keycallthyb")
        if (self.controller.thermalrunner.VIDEOON == True) and (self.controller.thermalrunner.THERMALON == True):
            print("thermal vision - cm up") #cm down will be set up as another button later, for now just cycle through colourmaps using cm_up
            self.controller.thermalrunner.cm_up()

        self.controller.thermalrunner.VIDEOON = True
        self.controller.thermalrunner.THERMALON = True
        self.videocanvas.itemconfigure(self.cantempmax, state='normal')
        self.videocanvas.itemconfigure(self.cantempmin, state='normal')
        self.videocanvas.itemconfigure(self.cantemp, state='normal')
        self.videocanvas.itemconfigure(self.canthermfps, state='normal')
        self.videocanvas.itemconfigure(self.canfps, state='normal')

    def keycallback(self):
        print("keycallback") #switch to plain video
        self.videocanvas.itemconfigure(self.cantempmax, state='hidden')
        self.videocanvas.itemconfigure(self.cantempmin, state='hidden')
        self.videocanvas.itemconfigure(self.cantemp, state='hidden')
        self.videocanvas.itemconfigure(self.canthermfps, state='hidden')
        self.videocanvas.itemconfigure(self.canfps, state='normal')
        self.controller.thermalrunner.THERMALON = False
        self.controller.thermalrunner.VIDEOON = True

vs = VideoStream(usePiCamera=True, resolution=(RESOLUTION[0], RESOLUTION[1])).start()

def main():
    mainapp = SensorApp()
    mainapp.mainloop()
    vs.stop()

main()
