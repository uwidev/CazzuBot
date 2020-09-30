import slots
import fileinput

if __name__ == "__main__":
    i = 0
    s = slots.Slots()
    f = open("data4.json", "w")

    
    
    while(i < 10000):
        s.slots(1)
        i += 1

    with f:
        print(s._winnings_data, file=f)

    
