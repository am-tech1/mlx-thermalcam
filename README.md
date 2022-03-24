# mlx-thermalcam
Raspberry Pi-powered thermal camera using the MLX90640 chipset and a 7" touchscreen display

Hardware requirements: Raspberry Pi, Pi Camera, MLX90640, and a touchscreen display. Currently set up for a 7" touchscreen display at 720x480 (mode 36). Also tested with a 3.2" inch touchscreen at 480x320 resolution, requires changing the FULLRESOLUTION variable.

Camera and i2c need to be enabled. Set i2c as fast as possible in config.txt: dtparam=i2c1_baudrate=1000000
 
Requires opencv, numpy, matplotlib, imutils and bsdz mlx90640-library - https://github.com/bsdz/mlx90640-library

controls:
NV - plain video, add an IR illuminator to have "night vision".

TV - plain thermal mode. press button again to cycle through colourmaps.

HV - hybrid vision mode, thermal overlaid over video. press button again to cycle through colourmaps.

! - take a snapshot

LK - lock thermal frame to video frame. this slows down video FPS to the same rate as thermal, but prevents the thermal from lagging behind video.

X - exit 

![image](https://user-images.githubusercontent.com/32528659/159824818-05c3bfaf-f209-4a35-a524-aad9a84466ef.png)
