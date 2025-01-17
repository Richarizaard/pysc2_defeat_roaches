from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import math
import numpy as np
import pandas as pd
import time

from pysc2.agents import base_agent
from pysc2.lib import actions
from pysc2.lib import features

_PLAYER_RELATIVE = features.SCREEN_FEATURES.player_relative.index
_PLAYER_FRIENDLY = 1
_PLAYER_NEUTRAL = 3  # beacon/minerals
_PLAYER_HOSTILE = 4
_NO_OP = actions.FUNCTIONS.no_op.id
_MOVE_SCREEN = actions.FUNCTIONS.Move_screen.id
_ATTACK_SCREEN = actions.FUNCTIONS.Attack_screen.id
_SELECT_ARMY = actions.FUNCTIONS.select_army.id
_SELECT_POINT = actions.FUNCTIONS.select_point.id
_NOT_QUEUED = [ 0 ]
_SELECT_ALL = [ 0 ]

ACTION_DO_NOTHING = 'donothing'
ACTION_SELECT_ARMY = 'selectarmy'
#ACTION_MOVE_SCREEN = 'movescreen'
ACTION_ATTACK = 'attack'


smart_actions = [
    ACTION_DO_NOTHING,
    ACTION_SELECT_ARMY,
    #ACTION_MOVE_SCREEN, 
    ACTION_ATTACK    
    ]

KILL_ROACH_REWARD = 10
MARINE_DEATH_REWARD = -1

# Taken from https://github.com/MorvanZhou/Reinforcement-learning-with-tensorflow
class QLearningTable:
    # Learning rate set to default 0.01 as it doesn't take long to learn to play
    # DefeatRoaches, or any minigame for that matter, so we don't need a high learning rate.
    # Take it slow and steady. Have also tried learning_rate = 0.05, 0.1.

    # Reward decay set to default 0.9. We still want future rewards to have a significant
    # impact when Q table is updated since DefeatRoaches is rather random. We don't want 
    # the randomness in the beginning to affect overall. Have also tried reward_decay = 0.85, 0.8.
    def __init__(self, actions, learning_rate=0.01, reward_decay=0.9, e_greedy=0.9):
        self.actions = actions  # a list
        self.lr = learning_rate
        self.gamma = reward_decay
        self.epsilon = e_greedy
        self.q_table = pd.DataFrame(columns=self.actions, dtype=np.float64)

    def choose_action(self, observation):
        # First, ensure state exists
        self.check_state_exist(observation)

        # Greedy policy we chose random
        if np.random.uniform() < self.epsilon:
            # choose best action
            state_action = self.q_table.ix[observation, :]
            
            # some actions have the same value
            state_action = state_action.reindex(np.random.permutation(state_action.index))
            
            action = state_action.idxmax()
        else:
            # choose random action
            action = np.random.choice(self.actions)
            
        return action

    def learn(self, s, a, r, s_):
        # First, ensure previous and current state exist
        self.check_state_exist(s_)
        self.check_state_exist(s)
        

        q_predict = self.q_table.ix[s, a]
        q_target = r + self.gamma * self.q_table.ix[s_, :].max()
        
        # update table
        self.q_table.ix[s, a] += self.lr * (q_target - q_predict)

    def check_state_exist(self, state):
        if state not in self.q_table.index:
            # append new state to q table
            self.q_table = self.q_table.append(pd.Series([0] * len(self.actions), index=self.q_table.columns, name=state))


class SmartDefeatRoaches( base_agent.BaseAgent ):
    
    def __init__(self):
        super( SmartDefeatRoaches, self ).__init__()
         
         # Setup Q table
        self.qlearn = QLearningTable(actions=list(range(len(smart_actions))))
        
        # Default scores       
        self.previous_killed_roach_score = 0
        self.previous_marine_death_score = 0
        self.previous_cumulative_score = 0

        # Set default actions
        self.previous_action = None
        self.previous_state = None

    def step( self, obs ):
        super( SmartDefeatRoaches, self ).step( obs )

        # Grab environment observation
        player_relative = obs.observation["screen"][_PLAYER_RELATIVE]

        # Cumulative score for roaches killed
        killed_roach_score = obs.observation[ 'score_cumulative' ][ 5 ]

        # Get roach locations | Roach size: 3x3
        roach_y, roach_x = (player_relative == _PLAYER_HOSTILE).nonzero()
        roach_count = len(roach_y) / 8.25

        # Get marine locations | Marine size: 2x2
        marine_y, marine_x = ( player_relative == _PLAYER_FRIENDLY ).nonzero()
        marine_count = len(marine_y) / 4

        # Set two different states: Not attacking and attacking based on previous action
        no_attack_state = 0
        attack_state = 1

        if( self.previous_action == smart_actions.index( ACTION_SELECT_ARMY ) ):
            state = attack_state
        elif( self.previous_action == smart_actions.index( ACTION_ATTACK ) ):
            state = attack_state
        else:
            state = no_attack_state

        # Set state
        current_state = [ state ] 

        # Get the number of roaches killed per loop
        roaches_killed_per_loop = ( killed_roach_score - self.previous_killed_roach_score ) / 10
            
        # Get score per loop
        score_per_loop = obs.observation[ 'score_cumulative' ][ 0 ] - self.previous_cumulative_score
        
        # Don't allow negative scores to be set
        if( score_per_loop < 0 ):
            score_per_loop = 0
            
        # Get score of marines that have died per loop
        marine_death_score = score_per_loop - roaches_killed_per_loop

        # Only reward after first episode
        if self.previous_action is not None:       
            # Reset reward
            reward = 0
            # Only accumulate reward if a roach was killed
            if killed_roach_score > self.previous_killed_roach_score:
                # Accumulate reward for each roach killed
                while( roaches_killed_per_loop > 0 ):
                    reward += KILL_ROACH_REWARD
                    roaches_killed_per_loop = roaches_killed_per_loop - 10   

            # Only accumulate reward if more marines were killed than previous marine death count
            #if marine_death_score < self.previous_marine_death_score:
            while( marine_death_score < 0 ):
                reward += MARINE_DEATH_REWARD
                marine_death_score = marine_death_score + 1

            # Add negative rewards for doing redunant tasks
            temp_prev_state = self.previous_state
            temp_prev_action = self.previous_action


            # Add rewards for choosing appropriate actions in different states, yeah I know it's ugly
            if( self.previous_state == [no_attack_state] and ( ( self.previous_action == smart_actions.index( ACTION_DO_NOTHING ) ) or ( self.previous_action == smart_actions.index( ACTION_SELECT_ARMY ) ) ) ) :
                reward += -5
            elif( self.previous_state == [attack_state] and ( ( self.previous_action == smart_actions.index( ACTION_DO_NOTHING ) ) or ( self.previous_action == smart_actions.index( ACTION_SELECT_ARMY ) ) ) ) :
                reward += -5 
            elif( self.previous_state == [no_attack_state] and self.previous_action == smart_actions.index( ACTION_ATTACK ) ):
                reward += 5
            elif( self.previous_state == [attack_state] and self.previous_action == smart_actions.index( ACTION_ATTACK ) ):
                reward += 5

            # Update Q table based on previous state, previous action, the reward accumulated, and the current state for target
            self.qlearn.learn(str(self.previous_state), self.previous_action, reward, str(current_state))

        # Chose action based on current state
        rl_action = self.qlearn.choose_action(str(current_state))
        action = smart_actions[rl_action]

        # Update previous variables for next step iteration
        self.previous_killed_roach_score = killed_roach_score
        self.previous_marine_death_score = marine_death_score
        self.previous_cumulative_score = obs.observation[ 'score_cumulative' ][ 0 ]
        self.previous_state = current_state
        self.previous_action = rl_action


        # Perform action
        if action == ACTION_DO_NOTHING:
            return actions.FunctionCall( _NO_OP, [] )

        elif action == ACTION_SELECT_ARMY:
            return actions.FunctionCall( _SELECT_ARMY, [ _SELECT_ALL ] )
        
        elif action == ACTION_ATTACK:
            # First, make sure attack is available based on the state
            if _ATTACK_SCREEN in obs.observation["available_actions"]:
              # No roach? no_op  
              if not roach_y.any():
                return actions.FunctionCall(_NO_OP, [])
              # Grab roach with max y coord 
              index = np.argmax(roach_y)
              # Set target coordinates
              target = [roach_x[index], roach_y[index]]
              # Perform action on target
              return actions.FunctionCall(_ATTACK_SCREEN, [_NOT_QUEUED, target])
            else: 
                return actions.FunctionCall( _NO_OP, [] )