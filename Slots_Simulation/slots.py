from copy import copy
from random import randint
from time import time
import fileinput

######################## PAYOUTS ########################
#########################################################
#################    combo     frogs   ##################
#################    7 7 7       25    ##################
#################    6 6 6       15    ##################
#################    5 5 5       15    ##################
#################    5 5 6       13    ##################
#################    4 4 4        7    ##################
#################    4 4 6        6    ##################
#################    3 3 3        5    ##################
#################    3 3 6        4    ##################
#################    2 2 2        3    ##################
#################    2 2 6        2    ##################
#################    1 1 ?        1    ##################
#################    1 ? ?        1    ##################
#########################################################
#########################################################

_SYMBOL_AMOUNT_IN_REEL = 5
_NUM_OF_REELS = 3

class Slots():
    # Minimum of 8 emotes required for this to work
    _emotes = [":x:", ":one:", ":two:", ":three:", ":four:", ":five:", ":six:", ":seven:"] # Change/comment out later
    _update_speed_secs = 1 # there can be two events (awaits) every second
    # For future designer(s): change this to change combo->payout
    # The last two payouts will be handled by a helper function
    _combo_payout = {
        _emotes[7]+_emotes[7]+_emotes[7] : 25,
        _emotes[6]+_emotes[6]+_emotes[6] : 15,
        _emotes[5]+_emotes[5]+_emotes[5] : 15,
        _emotes[5]+_emotes[5]+_emotes[6] : 13,
        _emotes[4]+_emotes[4]+_emotes[4] :  7,
        _emotes[4]+_emotes[4]+_emotes[6] :  6,
        _emotes[3]+_emotes[3]+_emotes[3] :  5,
        _emotes[3]+_emotes[3]+_emotes[6] :  4,
        _emotes[2]+_emotes[2]+_emotes[2] :  3,
        _emotes[2]+_emotes[2]+_emotes[6] :  2,
        _emotes[1]+_emotes[1]+_emotes[5] :  1,
        _emotes[1]+_emotes[1]+_emotes[4] :  1,
        _emotes[1]+_emotes[1]+_emotes[3] :  1,
        _emotes[1]+_emotes[1]+_emotes[2] :  1,
        _emotes[1]+_emotes[1]+_emotes[1] :  1,
        _emotes[1]+_emotes[1]+_emotes[0] :  1
        }

    _winnings_data = {
        _emotes[7]+_emotes[7]+_emotes[7] :  0,
        _emotes[6]+_emotes[6]+_emotes[6] :  0,
        _emotes[5]+_emotes[5]+_emotes[5] :  0,
        _emotes[5]+_emotes[5]+_emotes[6] :  0,
        _emotes[4]+_emotes[4]+_emotes[4] :  0,
        _emotes[4]+_emotes[4]+_emotes[6] :  0,
        _emotes[3]+_emotes[3]+_emotes[3] :  0,
        _emotes[3]+_emotes[3]+_emotes[6] :  0,
        _emotes[2]+_emotes[2]+_emotes[2] :  0,
        _emotes[2]+_emotes[2]+_emotes[6] :  0,
        _emotes[1]+_emotes[1]+_emotes[5] :  0,
        _emotes[1]+_emotes[1]+_emotes[4] :  0,
        _emotes[1]+_emotes[1]+_emotes[3] :  0,
        _emotes[1]+_emotes[1]+_emotes[2] :  0,
        _emotes[1]+_emotes[1]+_emotes[1] :  0,
        _emotes[1]+_emotes[1]+_emotes[0] :  0,
        "LOSS" : 0
    }


    def slots(self, credits):
        '''
        Runs the slot machine.
        '''

        reels = [[] for i in range(0, _NUM_OF_REELS)]
        self._assign_reels(reels)
        # The line at the bottom is disgusting. Change it when you get the chance.

        self._roll_reels(reels)


    def _assign_reels(self, reels):
        '''This assigns each reel a list of symbols. 
        
        It's designed so that no three straight symbols are the same
        '''

        for reel in reels:
            prev_index_1 = None
            prev_index_2 = None
            for i in range(0, _SYMBOL_AMOUNT_IN_REEL):
                current_index = randint(0, len(Slots._emotes)-1)
                while(current_index == prev_index_1 or current_index == prev_index_2):
                    current_index = randint(0, len(Slots._emotes)-1)
                prev_index_2 = prev_index_1
                prev_index_1 = current_index
                reel.append(Slots._emotes[current_index])


    def _roll_reels(self, reels):
        ''' Roll each reel for a certain amount of ticks '''
        bottom_slot0, bottom_slot1, bottom_slot2 = 2, randint(0, _SYMBOL_AMOUNT_IN_REEL - 4), randint(0, _SYMBOL_AMOUNT_IN_REEL - 4)
        reel0_ticks = randint(1, 2)
        reel1_ticks = reel0_ticks + randint(0,1)
        reel2_ticks = reel1_ticks + randint(0,1)

        slot_0 = None
        slot_1 = None
        slot_2 = None

        while(reel2_ticks >= 0):
            # This is currently designed to accomidate three reels
            # TODO: Make printing strings more modulare for different number of reels
            slot_0 = reels[0][(bottom_slot0 - 1) % 5]
            slot_1 = reels[1][(bottom_slot1 - 1) % 5]
            slot_2 = reels[2][(bottom_slot2 - 1) % 5]
            
            reel0_ticks -= 1
            reel1_ticks -= 1
            reel2_ticks -= 1

            if (reel0_ticks > 0):
                bottom_slot0 = (bottom_slot0 + 1) % 5
            if (reel1_ticks > 0):
                bottom_slot1 = (bottom_slot1 + 1) % 5
            if (reel2_ticks > 0):
                bottom_slot2 = (bottom_slot2 + 1) % 5


        payout = Slots._combo_payout.get(slot_0+slot_1+slot_2, 0)
        if (payout > 0):
            Slots._winnings_data[slot_0+slot_1+slot_2] += 1
        else:
            Slots._winnings_data["LOSS"] += 1