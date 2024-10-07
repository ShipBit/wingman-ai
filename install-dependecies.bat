@echo off
echo.
echo ##################################
echo ## Creating virtual environment ##
echo ##################################
echo.
IF NOT EXIST .venv (
    echo Creating virtual environment
    python -m venv .venv
)
echo Activating virtual environment
call .venv\Scripts\activate

echo.
echo #####################################
echo ## Installing project dependencies ##
echo #####################################
echo.
pip install -r requirements.txt

echo.
echo ###################################
echo ## Installing skill dependencies ##
echo ###################################
echo.
for /d %%d in (skills\*) do (
    echo ## Processing directory: %%d
    cd %%d
    IF NOT EXIST requirements.txt (
        echo requirements.txt not found in %%d, skipping
    ) ELSE (
        pip install -r requirements.txt
    )
    cd ..
    echo.
)
echo.
echo ##############
echo ## All done ##
echo ##############
echo.
pause