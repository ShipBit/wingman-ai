@echo off
echo ######################################
echo ## Copying skill to template folder ##
echo ######################################
echo.
set SKILL_FOLDER=uexcorp
rmdir /S /Q templates\skills\%SKILL_FOLDER%
echo Deleted old skill template.
echo.
echo __pycache__ > exclude_skill_copy.txt
echo Copied skills:
for /d %%d in (skills\%SKILL_FOLDER%) do (
    if /I not "%%~nxd"=="__pycache__" (
        echo - %%~nxd
        xcopy /E /I /Y "%%d" "templates\skills\%%~nxd\" /EXCLUDE:exclude_skill_copy.txt > nul
    )
)
del exclude_skill_copy.txt
echo.
set "NEWEST_FOLDER="
for /f "delims=" %%i in ('dir "%APPDATA%\ShipBit\WingmanAI" /ad /b /o-d') do (
    set "NEWEST_FOLDER=%%i"
    goto :found
)
:found
if exist "%APPDATA%\ShipBit\WingmanAI\%NEWEST_FOLDER%\skills\%SKILL_FOLDER%" (
    rmdir /S /Q "%APPDATA%\ShipBit\WingmanAI\%NEWEST_FOLDER%\skills\%SKILL_FOLDER%"
    echo Deleted skill in appdata dir.
) else (
    goto :notfound
)
goto :end
:notfound
echo No skill in appdata dir to delete.
:end
echo.
echo ##############
echo ## All done ##
echo ##############
echo.
