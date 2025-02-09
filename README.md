# pyDashcamViewer
Play dashcamvideos and show their gps position in realtime with python
<br>
<br>
<img src="https://github.com/Cynobs-repo/pydashcamviewer/blob/main/pyDashcamview_image.png" width="600">
<br><br>

> [!IMPORTANT]
> Only works with **VIOFO A229 Plus** dashcam mp4 video files. 
<br>
Can also work with other Novatek based dashcams but its not tested until now.<br>
If you have another type of (Viofo) dashcam, please try it out and post a comment. <br>
If you have a completely different cam and it doesn't work you can send me a video file of it and I will extend the script.<br>
<br>
  
✅ designed for windows (10/11) <br>
✅ standalone package available - no install needed <br>
✅ GPS position is displayed on openstreetmaps synchronized with the video file <br>

## How to install and setup

### the lazy way

Download all the pyDashcamplayer.7zip files and unzip them. 
<br>
Open the folder pyDashcamplayer and start the exe of the same name in it.

<br>

### build it 

> [!NOTE]
> You will need Python 3.6 to run the code.
<br>

While we are on a Windows system we can use winpython. First we download the appropriate Winpython package: 
https://sourceforge.net/projects/winpython/files/WinPython_3.6/3.6.8.0/WinPython64-3.6.8.0Zero.exe/download

unzip/extract it somewhere you like.
Open the WPy64-3680 folder and start the WinPython Command Prompt.exe

in the Command prompt window type:
```
python.bat -m pip install --upgrade pip
```

to update the old pip package in winpython. If you do not do this, the installation of opencv will fail.
then install needed packages with:
```
python.bat -m pip install opencv-python pillow folium cefpython3 pywin32
```

As soon as this is finished, copy the pydashcam folder and its contents to /WPy64-3680/python-3.6.8.amd64/
The file run_VE.bat is copied to the /WPy64-3680/scripts folder.

Now you can execute the run_VE.bat script and pyDashcamviewer starts.
<br>
<br>

If you want to build a exe file like in the aio package you can use autoit:
AutoIt is a simple tool for creating .exe files. Download AutoIt and install it.
https://www.autoitscript.com/site/autoit/downloads/
<br>
Create a file named pyDashcamViewer.au3 with the following content:
```
Run(@ScriptDir & "\scripts\run_VE.bat", @ScriptDir, @SW_SHOW)
````
<br>
Explanation:
<br>

> @ScriptDir returns the directory of the .exe file. <br>
> Run(...) starts the batch file in the scripts subfolder.<br>
<br><br>

After the installation of AutoIt: <br>

* Right-click on pyDashcamViewer.au3 <br>
* Select Compile Script (x64) <br>
* This will create a pyDashcamViewer.exe.<br>
<br>

This pyDashcamViewer.exe can now be used to start the run_VE.bat in the scripts folder.
