# irsdk Documentation - iRacing SDK for Python

Python 3 implementation of iRacing SDK can:

- Get session data (WeekendInfo, SessionInfo, etc...)
- Get live telemetry data (Speed, FuelLevel, etc...)
- Broadcast messages (camera, replay, chat, pit and telemetry commands)

Taken from [pyirsdk](https://github.com/kutu/pyirsdk/tree/master/tutorials).

## Tutorials

First thing you want when learning new library - shortest way to see it in action.

- Install pyirsdk
- Optional. Install ipython (interactive python interpretator with autocomplete functionality)
- Optional. Open C:\Users\...\Documents\iRacing\app.ini and change:

```ini
[Graphics]
...
fullScreen=0
```

Go to iRacing website, and start test session with any car and with "Centripetal Circuit" (this track loads faster than others)

Start Python with py command (or ipython if installed in step 2.) and type:

```bash
>>> import irsdk
>>> ir = irsdk.IRSDK()
>>> ir.startup()
<<< True
>>> ir['Speed']
<<< 0.0
```

When reading session data, you always must check it for existence first:

```bash
> > > if ir['WeekendInfo']:
> > > print(ir['WeekendInfo']['WeekendOptions']['StartingGrid'])
> > > <<< '2x2 inline pole on left'
> > > Most available variables (like ir['Speed']) with descriptions you can find here.
```

### Using irsdk script

When you are installing pyirsdk you also get irsdk.exe script in `X:\Python3X\Scripts` directory, which you can use for:

Dump current iRacing memory map to binary file `irsdk.exe --dump data.bin`

Parse dumped binary file to txt file `irsdk.exe --test data.bin --parse data.txt`

Parse current iRacing memory map to readable txt file `irsdk.exe --parse data.txt`

Now, when you write your own scripts, for test purposes you can pass binary file to irsdk, instead of keeping iRacing simulator running

```py
import irsdk
ir = irsdk.IRSDK()
ir.startup(test_file='data.bin')
print(ir['Speed'])
```

Note: data.bin can also be an IBT Telemetry file, use it if you need to read session data. To read IBT Telemetry samples you have to use irsdk.IBT Class.

### Base application

In this tutorial, you will learn how to create base of your own iRacing application using pyirsdk.
Entry point is at the bottom, at if **name** == '**main**': line.

```py
import irsdk
import time

# this is our State class, with some helpful variables
class State:
    ir_connected = False
    last_car_setup_tick = -1

# here we check if we are connected to iracing
# so we can retrieve some data
def check_iracing():
    if state.ir_connected and not (ir.is_initialized and ir.is_connected):
        state.ir_connected = False
        # don't forget to reset your State variables
        state.last_car_setup_tick = -1
        # we are shutting down ir library (clearing all internal variables)
        ir.shutdown()
        print('irsdk disconnected')
    elif not state.ir_connected and ir.startup() and ir.is_initialized and ir.is_connected:
        state.ir_connected = True
        print('irsdk connected')

# our main loop, where we retrieve data
# and do something useful with it
def loop():
    # on each tick we freeze buffer with live telemetry
    # it is optional, but useful if you use vars like CarIdxXXX
    # this way you will have consistent data from those vars inside one tick
    # because sometimes while you retrieve one CarIdxXXX variable
    # another one in next line of code could change
    # to the next iracing internal tick_count
    # and you will get incosistent data
    ir.freeze_var_buffer_latest()

    # retrieve live telemetry data
    # check here for list of available variables
    # https://github.com/kutu/pyirsdk/blob/master/vars.txt
    # this is not full list, because some cars has additional
    # specific variables, like break bias, wings adjustment, etc
    t = ir['SessionTime']
    print('session time:', t)

    # retrieve CarSetup from session data
    # we also check if CarSetup data has been updated
    # with ir.get_session_info_update_by_key(key)
    # but first you need to request data, before checking if its updated
    car_setup = ir['CarSetup']
    if car_setup:
        car_setup_tick = ir.get_session_info_update_by_key('CarSetup')
        if car_setup_tick != state.last_car_setup_tick:
            state.last_car_setup_tick = car_setup_tick
            print('car setup update count:', car_setup['UpdateCount'])
            # now you can go to garage, and do some changes with your setup
            # this line will be printed, only when you change something
            # and press apply button, but not every 1 sec
    # note about session info data
    # you should always check if data exists first
    # before do something like ir['WeekendInfo']['TeamRacing']
    # so do like this:
    # if ir['WeekendInfo']:
    #   print(ir['WeekendInfo']['TeamRacing'])

    # and just as an example
    # you can send commands to iracing
    # like switch cameras, rewind in replay mode, send chat and pit commands, etc
    # check pyirsdk.py library to see what commands are available
    # https://github.com/kutu/pyirsdk/blob/master/irsdk.py#L134 (class BroadcastMsg)
    # when you run this script, camera will be switched to P1
    # and very first camera in list of cameras in iracing
    # while script is running, change camera by yourself in iracing
    # and notice how this code changes it back every 1 sec
    ir.cam_switch_pos(0, 1)

if __name__ == '__main__':
    # initializing ir and state
    ir = irsdk.IRSDK()
    state = State()

    try:
        # infinite loop
        while True:
            # check if we are connected to iracing
            check_iracing()
            # if we are, then process data
            if state.ir_connected:
                loop()
            # sleep for 1 second
            # maximum you can use is 1/60
            # cause iracing updates data with 60 fps
            time.sleep(1)
    except KeyboardInterrupt:
        # press ctrl+c to exit
        pass

```
