import webrepl
try:
    webrepl.start()
except Exception:
    # Don't let a webrepl error stop the boot process
    pass