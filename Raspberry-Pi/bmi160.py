import time
from BMI160_i2c import Driver
def bmi160_accsave(name, num, port):
    sensor = Driver(0x68, port) # change address if needed
    sensor.set_accel_rate(12)
    a = 0
    acc = ''
    time_start = time.time()
    accwriter = open(name + '_' + str(time_start) + '.txt', 'w')
    while (a < num):
        if sensor.getIntDataReadyStatus():
            a = a + 1
            data = sensor.getAcceleration()
            acc = acc + str(data[0]) + ' ' + str(data[1]) + ' ' + str(data[2]) + ' ' + str(time.time()) + '\n'
        else:
            accwriter.write(acc)
            acc = ''
    print(num/(time.time() - time_start))

if __name__ == "__main__":
    bmi160_accsave(8000, 1)