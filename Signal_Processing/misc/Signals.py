import numpy as np
import scipy as scp
import sklearn as sk
import torch as pytorch

class Signals:
    """
    General Class used to handle all signal processing tasks.

    Attributes:
        parameters(np.array) : Parameters used to process signals.
    """
    def __init__(self, parameters):
        self.parameters = parameters
        print("constructor done")



if __name__ == "__main__":
    signal = Signals(np.array([0,0]))