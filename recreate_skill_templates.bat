@echo off
echo #######################################
echo ## Copying skills to template folder ##
echo #######################################
echo.
rmdir /S /Q templates\skills\uexcorp_beta
mkdir templates\skills\uexcorp_beta
echo Deleted all old skill templates.
echo.
echo __pycache__ > exclude_skill_copy.txt
echo Copied skills:
for /d %%d in (skills\uexcorp_beta) do (
    if /I not "%%~nxd"=="__pycache__" (
        echo - %%~nxd
        xcopy /E /I /Y "%%d" "templates\skills\%%~nxd\" /EXCLUDE:exclude_skill_copy.txt > nul
    )
)
del exclude_skill_copy.txt
echo.
echo ##############
echo ## All done ##
echo ##############
echo.
