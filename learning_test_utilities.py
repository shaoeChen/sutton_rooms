# -*- coding: utf-8 -*-
"""
Created on Tue Oct 24 15:57:52 2017

@author: momos_000
"""
# Shared utilities for testing various RL schemes on the Sutton Room World
import datetime
import pickle as pkl
import os.path
import numpy as np
import matplotlib.pyplot as plt
from room_world import *

def learning_parameters():
    epsilon = 0.2
    gamma = 0.9
    alpha = 1./8. # matching Sutton
    return epsilon, gamma, alpha

class QTable():
    """Class for storing q-values in a table.
    """
    def __init__(self,state_space,num_actions):
        self.num_actions = num_actions
        self.state_space = state_space
        self.table = {}
        for s in state_space:
            # Q-value is called by q_func.table[str(s)][a], where:
            #   q_func is a QTable object
            #   s is the agent position as an ndarray
            #   a is the index of the action
            self.table[str(s)] = np.zeros(num_actions)
            
    def __call__(self,state):
        """Returns the set of q-values stored for the given state.
        """
        return self.table[str(state)]


def create_hallway_options(environment):
    """Makes deterministic option policies
       Finds hallway locations and makes action policies to go to the hallways
       from either adjacent room
    """
    nm          = environment.numbered_map
    hall_coords = np.argwhere(nm==0)
    adjacent    = [[1,0],[-1,0],[0,1],[0,-1]] # down, up, right, left
    options     = []
    for c in hall_coords:
        surrounding  = [nm[tuple(c+adj)] for adj in adjacent] # list adjacent
                                                              # incl. walls
        valid_rooms  = [r for r in surrounding if not (r==[-1,0]).any()]
        valid_states = np.argwhere(nm==valid_rooms[0])
        for room in valid_rooms:
            if not room == valid_rooms[0]:
                valid_states = np.concatenate((valid_states,np.argwhere(nm==room)),axis=0)
        for i,l in enumerate(nm):
            for j,r in enumerate(l):
                if r==0: # it's a hallway at position (i,j)
                    surr = [nm[tuple(np.array([i,j])+adj)] for adj in adjacent]
                    inclusion = np.array([(room in surr) for room in valid_rooms])
                    if inclusion.any() and not inclusion.all():
                        valid_states = np.concatenate((valid_states,np.array([[i,j]])),axis=0)
                        # add hallway to valid if it connects to the rooms to 
                        # others but not each other
        policy = -np.ones(nm.shape)
        if surrounding[0] == -1: # down is wall, so hallway is horizontal
            for i in range(policy.shape[0]):
                for j in range(policy.shape[1]):
                    if [i,j] in valid_states.tolist():
                        if c[0]==i: # hallway and point aligned horizontally
                            if c[1]>j: # hallway is right of the point
                                policy[i,j] = RIGHT
                            else: # hallway is left of the point
                                policy[i,j] = LEFT
                        else: # not aligned. move to alignment
                            if c[0]<i: # hallway is above
                                policy[i,j] = UP
                            else:
                                policy[i,j] = DOWN
        else: # right is room, so hallway is horizontal
            for i in range(policy.shape[0]):
                for j in range(policy.shape[1]):
                    if [i,j] in valid_states.tolist():
                        if c[1]==j: # hallway and point are aligned vertically
                            if c[0]>i: # hallway is below the point
                                policy[i,j] = DOWN
                            else: # hallway is above the point
                                policy[i,j] = UP
                        else:
                            if c[1]>j: # hallway is right of point
                                policy[i,j] = RIGHT
                            else: # hallway is left of point
                                policy[i,j] = LEFT

        options.append(Option(policy, valid_states, c)) # c is termination st
    return options
   

def discounted_return(rewards,gamma):
    try:
        discounted = 0.0
        last_discount = 1.0
        for reward_set in rewards:
            gamma_mask = [gamma**t for t in range(len(reward_set))] #len(reward_set) will work if rewards is a list of lists (from planning agent)
            discounted+= np.dot(reward_set,gamma_mask) * last_discount * gamma
            last_discount = last_discount * gamma_mask[-1]
    except TypeError: # didn't work, so rewards is a list of floats - no recursion.
        gamma_mask = [gamma**t for t in range(len(rewards))]
        discounted = np.dot(rewards,gamma_mask)
    return discounted


def q_learning_update(gamma, alpha, q_vals, cur_state, action, next_state, reward):
    """
    Inputs:
        gamma: discount factor
        alpha: learning rate
        q_vals: q value table
        cur_state: current state
        action: action taken opcurrent state
        next_state: next state results from taking `action` in `cur_state`
        reward: reward received from this transition
    
    Performs in-place update of q_vals table to implement one step of Q-learning
    """
    target = reward + gamma * np.max(q_vals[str(next_state)])
    td_err = target-q_vals[str(cur_state)][action]
    q_vals[str(cur_state)][action] = q_vals[str(cur_state)][action] + alpha * td_err
    return td_err

def q_learning_update_option_sequence(gamma, alpha, q_vals, states, rewards, option_index):
    """Does an update like q_learning_update, but using a sequence of states,
       actions, and rewards obtained from following an option to termination.
       USED FOR SMDP Q-LEARNING WITHOUT PLAN
    """
    td_errs = []
    T = len(rewards)
    for t in range(T):
        td_errs.append(q_learning_update(gamma, alpha, q_vals, states[t], \
            option_index, states[t+1], discounted_return(rewards[t:],gamma)))
    return td_errs

def q_learning_update_plan_options(gamma, alpha, q_vals, states, rewards, plan_option_index):
    """Does an update like q_learning_update, but using a sequence of states,
       actions, and rewards obtained from following an option to termination.
       USED FOR SMDP Q-LEARNING WITH PLAN
    """
    td_errs = []
    T = len(rewards)
    for t in range(T-1):
        td_errs.append(q_learning_update(gamma, alpha, q_vals, states[t], \
            plan_option_index, states[t+1], discounted_return(rewards[t:],gamma)))
    return td_errs

          
def greedy_eval(agent, gamma, max_steps, evals=10):
    """evaluate greedy policy w.r.t current q_vals
       max_steps is used by smdp agent an q agent.
        -> for smdp, it is the number of options that can be chosen.
        -> for q, it is the number of primitive actions that can be chosen.
    """
    test_env = RoomWorld()
    test_env.add_agent(agent)
    #steps = 0
    ret = 0.
    steps = 0.
    try: # Planning Agent
        for i in range(evals):
            initial_state = test_env.reset(random_placement=True)
            _ = agent.make_plan(initial_state)
            states, actions, rewards, done = test_env.step_plan(agent.sebango)
            ret += discounted_return(rewards,gamma) #np.sum([np.sum([r for r in rewards if not r==[None]])])
            steps += np.sum([len(s) for s in states])
    except(AttributeError): #s-MDP Agent
        try:
            for _ in range(evals):
                prev_state = test_env.reset(random_placement=True)
                reward_record = []
                done = False
                for s in range(max_steps):
                    option = agent.pick_option_greedy_epsilon(prev_state,eps=0.0)
                    states, actions, rewards, done = test_env.step_option(option)
                    reward_record.append(rewards) # ret += np.sum(rewards)
                    prev_state = states[-1]
                    steps += len(states)
                    if done:
                        break
                ret += discounted_return(reward_record,gamma)
        except(AttributeError): # Flat Q-learning Agent
            for i in range(evals):
                prev_state = test_env.reset(random_placement=True)
                reward_record = []
                done = False
                for s in range(max_steps):
                    action = agent.greedy_action(prev_state)
                    state, reward, done = test_env.step(action)
                    reward_record.append(reward) # ret += reward
                    prev_state = state
                    steps += 1
                    if done:
                        break
                ret += discounted_return(reward_record,gamma)
    finally:
        return (ret/evals, steps/evals)
    
#def test_agent(agent,step_limit=2):
#    test_env = RoomWorld()
#    test_env.add_agent(agent)
#    actions = []
#    states  = []
#    rewards = []
#    states.append(test_env.reset(random_placement=True))
#    for i in range(step_limit):
#        a = agent.greedy_action(states[i])
#        st,r,done = test_env.step(a)
#        actions.append(a)
#        states.append(st)
#        rewards.append(r)
#        if done:
#            break
#    return np.array(states),np.array(actions),np.array(rewards)


def arrayify_q(q_func,walkability):
    # Put the q-function into an array
    h,w = walkability.shape
    Q = np.zeros((h,w,q_func.num_actions))
    for k in q_func.table.keys():
        ij = k.lstrip("[ ").rstrip(" ]").split(" ")
        i  = ij[0]
        j  = ij[-1]
        Q[int(i),int(j)] = q_func.table[k]
    return Q

def plot_greedy_policy(q_func,walkability,action_directions=np.array([[1,0],[0,1],[-1,0],[0,-1]])):
    # ASSUMES THAT q_func AND walkability HAVE THE SAME DIMENSIONS ALONG AXES
    # 0 AND 1!
    h,w = walkability.shape
    Q = arrayify_q(q_func,walkability)
    G = np.argmax(Q,axis=2)  # table of greedy action indices (i.e., policy lookup table)
    D = np.zeros((h,w,action_directions.shape[1])) # table of greedy direction
                                                   # of motion
    for i,r in enumerate(G):
        for j,c in enumerate(r):
            if walkability[i][j]:
                D[i][j] = action_directions[c]
            else:
                D[i][j] = np.zeros_like(action_directions[0])
    x=np.linspace(0,12,13)
    x,y=np.meshgrid(x,x)
    plt.quiver(x,-y,D[:,:,0],D[:,:,1],scale_units="xy",scale=1.25) # Rooms were mapped y-down.
    plt.show()
    
    return Q,G,D


def timeStamped(fname, fmt='%Y%m%d-%H%M_{fname}'):
    return datetime.datetime.now().strftime(fmt).format(fname=fname)

def final_plots(env,ag,hist,avg_period=100):
    avg_hist = np.zeros((hist.shape[0]-avg_period,hist.shape[1]))
    for i in range(avg_hist.shape[0]):
        avg_hist[i,:] = np.mean(hist[i:i+avg_period,:],axis=1)
    print("Plot update amount") 
    plt.plot(hist[:,0],hist[:,1],avg_hist[:,0],avg_hist[:,1]); plt.show()
    print("Plot training return")
    plt.plot(hist[:,0],hist[:,2],avg_hist[:,0],avg_hist[:,2]); plt.show()
    print("Plot test return")
    plt.plot(hist[:,0],hist[:,3],avg_hist[:,0],avg_hist[:,3]); plt.show()
    print("Plot test steps")
    plt.plot(hist[:,0],hist[:,4],avg_hist[:,0],avg_hist[:,4]); plt.show()
    Q,G,D = plot_greedy_policy(ag.q_func, env.walkability_map)
    return Q

def pickle_results(obj, fname):    
    if os.path.isfile(fname):
        print("File {} already exists. Please move to avoid data loss.".format(fname))
        return "NOT SAVED"
    else:
        with open(fname,"wb") as f:
            pkl.dump(obj,f)
        return fname
    
def plot_and_pickle(env,ag,hist):
    print("Plotting results")
    Q = final_plots(env,ag,hist)
    # save files with check inside pickle_results
    print("Pickling data")
    filename = timeStamped("training-history.pkl")
    saved    = pickle_results(hist,filename)
    print("  --training history saved: {}".format(saved))
    filename = timeStamped("qfunc.pkl")
    saved    = pickle_results(Q,filename)
    print("  --Q-function ndarray saved: {}".format(saved))