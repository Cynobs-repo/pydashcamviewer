@echo off
for /F "tokens=1-3 delims=:." %%A in ("%time%") do (
  set "hour=%%A"
  set "minute=%%B"
  set "sekunde=%%C"
)
set "zeit=%stunde%:%minute%:%sekunde%"
set startupname=rundashcamscript
title "%startupname%-%zeit%"
call "%~dp0env_for_icons.bat"  %*

:RUNIT
SETLOCAL ENABLEDELAYEDEXPANSION
SET count=1
FOR /F "tokens=* USEBACKQ" %%G IN (`call "%WINPYDIR%\python.exe"  "%WINPYDIR%\pydashcam\run.py" "%zeit%" %*`) DO (
  SET var!count!=%%G
  SET /a count=!count!+1
)
SET /a count=!count!-1
@echo on
ECHO !var%count%!
@echo off

IF "!var%count%!"=="dashcam_restart" goto RUNIT
IF "!var%count%!"=="dashcam_close" goto ENDE

ENDLOCAL


:ENDE

