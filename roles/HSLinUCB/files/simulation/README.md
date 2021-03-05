# HSLinUCB simulation

This is the Jupyter notebook used in the paper Horizontal Scaling using Contextual Bandits.

These notebook was used in the simulated section of the paper

## Installation
It is better to create a dedicated python environment as some external libraries will be installed.

These notebooks were tested with python 3.6.12 in Conda.

1- Create a Conda environment:

conda create --name hslinucb python=3.6.12

2- Activate your python environment:

conda activate hslinucb

3- Install the python dependencies:

pip install -r requirements.txt

4- Start the Jupyter notebook server:

jupyter-notebook

A browser will automaticaly loads the simulation notebook

## Simulation notebook details

12 notebooks are available and are associated with the binaries files generated during experiments for the paper.

Graph ColdStart.ipynb:

This notebook computes stats and display graphical results for the cold-start mode in the paper simulated section. The binary files used are those which ended with *_coldstart.bin. 

Graph HotStart Seen.ipynb:

Similary to the ColdStart.ipynb but for the hot-start with seen contexts mode in the paper simulated section. The binary files used are those which ended with *_hotstart_seen.bin

Graph HotStart UnSeen.ipynb:

Same as Graph HotStart Seen.ipynb but for the hot-start with unseen contexts mode in the paper simulated section. The binary file used are those which ended with *_hotstart_unseen.bin

hslinucb_coldstart.ipynb , hslinucb_hotstart_seen.ipynb and hslinucb_hotstart_unseen.ipynb:

These notebooks launch the simulated experiments for the cold-start, the hot-start with seen contexts and the hot-start with unseen contexts for the HSLinUCB algorithm.

The defaults hslinucb_*.bin binary files will be overwritten by these notebooks

A warning will be displayed at the beginning of the playbook. This warning does not break the notebook and will be fixed in the next version.

Note: You have to launch hslinucb_coldstart.ipynb before hslinucb_hotstart_seen.ipynb or hslinucb_hotstart_unseen.ipynb to generate the hslinucb model.

qlearning_coldstart.ipynb, qlearning_hotstart_seen.ipynb adn qlearning_hotstart_unseen.ipynb:

These notebooks launch the simulated experiments for the cold-start, the hot-start with seen contexts and the hot-start with unseen contexts for the Q-Learning algorithm.

The defaults qlearning_*.bin binary files will be overwritten by these notebooks

A warning will be displayed at the beginning of the playbook. This warning does not break the notebook and will be fixed in the next version.

Note: You have to launch qlearning_coldstart.ipynb before qlearning_hotstart_seen.ipynb or qlearning_hotstart_unseen.ipynb to generate the qlearning model.

dqn_cold_start.ipynb, dqn_hotstart_seen.ipynb and dqn_hotstart_unseen.ipynb:

These notebooks launch the simulated experiments for the cold-start, the hot-start with seen contexts and the hot-start with unseen contexts for the Deep Q-Learning algorithm.

The defaults dqn_*.bin binary files will be overwritten by these notebooks

A warning will be displayed at the beginning of the playbook. This warning does not break the notebook and will be fixed in the next version.

Note: You have to launch dqn_coldstart.ipynb before dqn_hotstart_seen.ipynb or dqn_hotstart_unseen.ipynb to generate the Deep Q-Learning model.
