# -*- coding: utf-8 -*-
"""
2017, LAAS/CNRS
@author: Rohan Budhiraja
"""

from __future__ import print_function

import numpy as np
from numpy import eye

# import pinocchio as se3
from pinocchio import Motion, rnea

# from pinocchio.robot_wrapper import RobotWrapper
import example_robot_data

from dynamic_graph import plug
from dynamic_graph.sot.core.matrix_util import matrixToTuple
from dynamic_graph.sot.core.meta_tasks_kine import (
    MetaTaskKine6d,
    MetaTaskKineCom,
    gotoNd,
)
from dynamic_graph.sot.core.sot import SOT
from dynamic_graph.sot.dynamic_pinocchio import fromSotToPinocchio
from dynamic_graph.sot.dynamic_pinocchio.humanoid_robot import HumanoidRobot
from dynamic_graph.sot.torque_control.torque_offset_estimator import (
    TorqueOffsetEstimator as TOE,
)

# ______________________________________________________________________________
# ******************************************************************************
#
# 1)  The simplest robot task: Just go and reach a point
# 2)  While performing this task:
#                  find the torque values and feed them to the sensor calibration entity.
# 3)  Confirm that the offsets being calculated are correct.
# ______________________________________________________________________________
# ******************************************************************************

# Requires sot-dynamic-pinocchio

# -----------------------------------------------------------------------------

dt = 5e-3
robotName = "TALOS"
OperationalPointsMap = {
    "left-wrist": "arm_left_7_joint",
    "right-wrist": "arm_right_7_joint",
    "left-ankle": "leg_left_5_joint",
    "right-ankle": "leg_right_5_joint",
    "gaze": "head_2_joint",
    "waist": "root_joint",
    "chest": "torso_2_joint",
}
initialConfig = (
    0.0,
    0.0,
    0.648702,
    0.0,
    0.0,
    0.0,  # Free flyer
    0.0,
    0.0,
    -0.453786,
    0.872665,
    -0.418879,
    0.0,  # Left Leg
    0.0,
    0.0,
    -0.453786,
    0.872665,
    -0.418879,
    0.0,  # Right Leg
    0.0,
    0.0,  # Chest
    0.261799,
    0.17453,
    0.0,
    -0.523599,
    0.0,
    0.0,
    0.1,
    0.0,  # Left Arm
    # 0., 0.,0.,0., 0.,0.,0.,                         # Left gripper
    -0.261799,
    -0.17453,
    0.0,
    -0.523599,
    0.0,
    0.0,
    0.1,
    0.0,  # Right Arm
    # 0., 0.,0.,0., 0.,0.,0.,                         # Right gripper
    0.0,
    0.0,  # Head
)

pinocchioRobot, _, urdfPath, _ = example_robot_data.load_full("talos", display=True)
pinocchioRobot.initDisplay(loadModel=True)
pinocchioRobot.display(fromSotToPinocchio(initialConfig))

robot = HumanoidRobot(
    robotName,
    pinocchioRobot.model,
    pinocchioRobot.data,
    initialConfig,
    OperationalPointsMap,
)

njoints = pinocchioRobot.model.nv - 6
sot = SOT("sot")
sot.setSize(robot.dynamic.getDimension())
plug(sot.control, robot.device.control)

# ------------------------------------------------------------------------------
# ---- TASKS -------------------------------------------------------------------

taskRH = MetaTaskKine6d("rh", robot.dynamic, "rh", robot.OperationalPointsMap["right-wrist"])
handMgrip = eye(4)
handMgrip[0:3, 3] = (0.1, 0, 0)
taskRH.opmodif = matrixToTuple(handMgrip)
taskRH.feature.frame("desired")

taskLH = MetaTaskKine6d("lh", robot.dynamic, "lh", robot.OperationalPointsMap["left-wrist"])
taskLH.opmodif = matrixToTuple(handMgrip)
taskLH.feature.frame("desired")

# --- STATIC COM (if not walking)
taskCom = MetaTaskKineCom(robot.dynamic)
robot.dynamic.com.recompute(0)
taskCom.featureDes.errorIN.value = robot.dynamic.com.value
taskCom.task.controlGain.value = 10

# --- CONTACTS
# define contactLF and contactRF

contactLF = MetaTaskKine6d("contactLF", robot.dynamic, "LF", robot.OperationalPointsMap["left-ankle"])
contactLF.feature.frame("desired")
contactLF.gain.setConstant(10)
contactLF.keep()

contactRF = MetaTaskKine6d("contactRF", robot.dynamic, "RF", robot.OperationalPointsMap["right-ankle"])
contactRF.feature.frame("desired")
contactRF.gain.setConstant(10)
contactRF.keep()

targetRH = (0.5, -0.2, 1.0)
targetLH = (0.5, 0.2, 1.0)

# addRobotViewer(robot, small=False)
# robot.viewer.updateElementConfig('zmp',target+(0,0,0))

gotoNd(taskRH, targetRH, "111", (4.9, 0.9, 0.01, 0.9))
gotoNd(taskLH, targetLH, "111", (4.9, 0.9, 0.01, 0.9))
sot.push(contactRF.task.name)
sot.push(contactLF.task.name)
sot.push(taskCom.task.name)
sot.push(taskLH.task.name)
sot.push(taskRH.task.name)

toe = TOE("test_entity_toe")
id4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)
epsilon = 0.1
ref_offset = 0.1
tau_offset = np.asarray((ref_offset,) * njoints).squeeze()
toe.init(urdfPath, id4, epsilon, OperationalPointsMap["waist"], OperationalPointsMap["chest"])
plug(robot.device.state, toe.base6d_encoders)
toe.gyroscope.value = (0.0, 0.0, 0.0)

gravity = Motion.Zero()
gravity.linear = np.asarray((0.0, 0.0, -9.81))

# -------------------------------------------------------------------------------
# ----- MAIN LOOP ---------------------------------------------------------------
# -------------------------------------------------------------------------------
robot.device.increment(dt)
np.set_printoptions(suppress=True)


def runner(n):
    for i in range(n):
        q_pin = fromSotToPinocchio(robot.device.state.value)
        q_pin[0, :6] = 0.0
        q_pin[0, 6] = 1.0
        nvZero = np.asarray((0.0,) * pinocchioRobot.model.nv)
        tau = np.asarray(rnea(pinocchioRobot.model, pinocchioRobot.data, q_pin, nvZero, nvZero)).squeeze()
        toe.jointTorques.value = tau_offset + tau[6:]
        pinocchioRobot.forwardKinematics(q_pin)
        toe.accelerometer.value = np.asarray((pinocchioRobot.data.oMi[15].inverse() * gravity).linear).squeeze()
        toe.jointTorquesEstimated.recompute(robot.device.state.time)

        robot.device.increment(dt)
        pinocchioRobot.display(q_pin)


runner(10)
toe.computeOffset(100, 1.0)
runner(100)
runner(1000)

print("The desired offset is", tau_offset)
print("The obtained offset is", toe.getSensorOffsets())
print(
    "The test is passed: ",
    (np.absolute(np.absolute(np.asarray(toe.getSensorOffsets())).max() - ref_offset) < epsilon),
)
