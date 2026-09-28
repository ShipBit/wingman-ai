@echo off
setlocal
set "RC=1"
if not defined AppData goto :failure
set "DEST=%AppData%\ShipBit\WingmanAI\custom_skills\sc_accountant"
for %%F in (main.py default_config.yaml erp.py erp_skill.py erp_sharing.py erp_reader_client.py accountant_ui\qrcodegen.py erp_ui\index.html erp_ui\app.js erp_ui\style.css) do (
    if not exist "%~dp0%%F" goto :incomplete
)
echo Fully close Wingman AI before installing. Run as your normal Windows user.
echo Installing SC Accountant to %DEST%...
robocopy "%~dp0." "%DEST%" /E /IS /IT /XF install.bat TESTER_README.md /XD __pycache__ /NJH /NJS /NFL /NDL /NC /NS /NP
set "RC=%errorlevel%"
if %RC% geq 8 goto :failure
set "RC=0"
echo Install complete! Restart Wingman and enable Personal ERP in your profile.
echo Enable and configure SC Log Reader 0.5.0 or newer in that same profile.
echo Accountant connects automatically. Leave its reader database setting blank.
echo Ask Wingman to open your accounting dashboard.
goto :end
:incomplete
echo ERROR: Incomplete package. Extract the entire ZIP before installing.
goto :end
:failure
echo ERROR: Install failed. Close Wingman and check that AppData is writable.
:end
pause
endlocal & exit /b %RC%
