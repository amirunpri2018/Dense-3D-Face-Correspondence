#!/usr/bin/env python
# coding: utf-8

# # Dense 3D Face Correspondence

# In[1]:


import os
os.environ["MKL_NUM_THREADS"] = "12"
os.environ["NUMEXPR_NUM_THREADS"] = "12"
os.environ["OMP_NUM_THREADS"] = "12"


# In[2]:


import pdb
import numpy as np
from collections import defaultdict
import time, warnings
import re
import threading
import cv2
import ipyvolume as ipv
import scipy
from math import cos, sin
from scipy import meshgrid, interpolate
import pdb
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from scipy.spatial import ConvexHull, Delaunay
import numpy as np
from scipy.interpolate import griddata

warnings.filterwarnings("ignore")


#Read each face data, normalize it and get the interpolation it in a parallel fashion
def get_data(file_path,var_name):
    #global points and grid data structure which will be modified by all threads
    global face_points
    global grid_data
    holder = []
    #reading face data from path
    with open(file_path, "r") as vrml:
        for line in vrml:
            a = line.strip().strip(",").split()
            if len(a) == 3:
                try:
                    holder.append(list(map(float, a)))
                except:
                    pass
    x,y,z = zip(*holder)
    x = np.array(x)
    y = np.array(y)
    z = np.array(z)
    holder = np.array(holder)
    #normalizing face
    maxind = np.argmax(holder[:,2])
    nosex = holder[maxind,0]
    nosey = holder[maxind,1]
    nosez = holder[maxind,2]
    holder = holder - np.array([nosex, nosey, nosez])
    face_points[var_name] = holder
    # grid data extraction
    x1, y1, z1 = map(np.array, zip(*holder))
    grid_x, grid_y = np.mgrid[np.amin(x1):np.amax(x1):0.5, np.amin(y1):np.amax(y1):0.5]
    grid_z = griddata((x1, y1), z1, (grid_x, grid_y), method='linear')
    grid_data[var_name] = [grid_x, grid_y, grid_z]

# ## Sparse Correspondence Initialization

# ## Seed points sampling using mean 2D convex hull



def hull72(points, nosex, nosey, nosez):
    newhull = [[nosex, nosey, nosez]]
    for theta in range(0, 360, 5):
        fx = 200 * cos(theta * np.pi / 180)
        fy = 200 * sin(theta * np.pi / 180)
        nearest_point = min(zip(points[:, 0], points[:, 1], points[:, 2]), key=lambda p:(p[0] - fx)**2 + (p[1] - fy)**2)
        newhull.append(nearest_point)
    return newhull


def get_hull(points):
    maxind = np.argmax(points[:,2])
    # coordinates of nose, nosex = x coordinate of nose, similarly for nosey and nosez
    nosex = points[maxind,0]
    nosey = points[maxind,1]
    nosez = points[maxind,2]
    hull = np.array(hull72(points, nosex,nosey,nosez))
    return hull


# ## Delaunay Triangulation


def triangulation(hull):
    points2D = np.vstack([hull[:,0],hull[:,1]]).T
    tri_hull = Delaunay(points2D)
    return tri_hull


# ## Geodesic Patch Extraction


def get_all_patches_for_face(face_index, hull, triangles):
    from itertools import combinations
    points = face_points["face"+str(face_index)]
    patch_width = 5 * rho
    def distance(x,y,z,x1,y1,z1,x2,y2,z2):
        a = (y2-y1)/(x2-x1)
        b = -1
        c = y2-x2*(y2-y1)/(x2-x1)
        return abs(a*x+b*y+c)/(a**2+b**2)**0.5

    all_patches = []
    for t1,t2 in combinations(triangles,r=2): #pairwise triangles
        if len(set(t1)&set(t2))==2:           #triangles with a common edge
            patch_list = []
            a_ind, b_ind = list(set(t1)&set(t2))
            x1, y1, z1 = hull[a_ind,:]
            x2, y2, z2 = hull[b_ind,:]
            for x,y,z in points: #loop over all points to find patch points
                if (x-x1/2-x2/2)**2+(y-y1/2-y2/2)**2<(x1/2-x2/2)**2+(y1/2-y2/2)**2 and distance(x,y,z,x1,y1,z1,x2,y2,z2)<patch_width:
                    patch_list.append([x,y,z])
            if len(patch_list)==0:
                #print("ALERT: NO PATCH FOR AN EDGE!!!!")
                pass
            all_patches.append(np.array(patch_list))
    global patches
    for edge_index in range(len(all_patches)):
        patches["edge" + str(edge_index)].append(all_patches[edge_index])


def update_patches(hull, triangles):
    threads = []
    for face_index in range(1, len(file_paths)+1):
        thread = threading.Thread(target=get_all_patches_for_face, args=(face_index, hull, triangles))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()


# takes in a point and the patch it belongs to and decides whether it is a keypoint (ratio of largest two eigenvalues on the covariance matrix of its local surface) or not
def is_keypoint(point, points):
    threshold = 7 * rho
    nhood = points[(np.sum(np.square(points-point),axis=1)) < threshold**2]
    try:
        nhood = (nhood - np.min(nhood, axis=0)) / (np.max(nhood, axis=0) - np.min(nhood, axis=0))
        covmat = np.cov(nhood)
        eigvals = np.sort(np.abs(np.linalg.eigvalsh(covmat)))
        ratio = eigvals[-1]/(eigvals[-2]+0.0001)
        return ratio>30 #eigen_ratio_threshold #/ 5
    except Exception as e:
        return False


def get_keypoints_from_patch(edge_index):
    global keypoints
    edge_patches = patches["edge" + str(edge_index)]
    edge_keypoints = []
    for patch in edge_patches:
        #print(patch.shape)
        if patch.shape[0]:
            patch_keypoints = patch[np.apply_along_axis(is_keypoint, 1, patch, patch)] # keypoints in `patch`
        else:
            patch_keypoints = []
        edge_keypoints.append(patch_keypoints)
    keypoints["edge" + str(edge_index)] = edge_keypoints



def update_keypoints(patches):
    threads = []
    for edge_index in range(1, len(patches)+1):
        thread = threading.Thread(target=get_keypoints_from_patch, args=(edge_index,))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()



def get_normal(x, y, grid_x, grid_y, grid_z):
    '''
      3
    1   2
      4
    x, y are coordinates of the point for which the normal has to be calculated
    '''
    i = (x - grid_x[0, 0]) / (grid_x[1, 0] - grid_x[0, 0])
    j = (y - grid_y[0, 0]) / (grid_y[0, 1] - grid_y[0, 0])
    i,j = int(round(i)), int(round(j))
    if (not 0 <= i < grid_x.shape[0]-1) or (not 0 <= j < grid_y.shape[1]-1):
        warnings.warn("out of bounds error")
        #pdb.set_trace()
        return "None"
    point1 = (grid_x[i-1, j], grid_y[i-1, j], grid_z[i-1, j])
    point2 = (grid_x[i+1, j], grid_y[i+1, j], grid_z[i+1, j])
    point3 = (grid_x[i, j-1], grid_y[i, j-1], grid_z[i, j-1])
    point4 = (grid_x[i, j+1], grid_y[i, j+1], grid_z[i, j+1])
    a1, a2, a3 = [point2[x] - point1[x] for x in range(3)]
    b1, b2, b3 = [point3[x] - point4[x] for x in range(3)]
    normal = np.array([a3*b2, a1*b3, -a1*b2])
    return normal/np.linalg.norm(normal)




def get_keypoint_features(keypoints, face_index):
    feature_list = [] # a list to store extracted features of each keypoint
    final_keypoints = [] # remove unwanted keypoints, like the ones on edges etc
    for point in keypoints:
        point_features = []
        x, y, z = point
        points = face_points["face" + str(face_index)]
        grid_x, grid_y, grid_z = grid_data["face" + str(face_index)]
        threshold = 5 * rho
        nhood = points[(np.sum(np.square(points-point), axis=1)) < threshold**2]
        xy_hu_moments = cv2.HuMoments(cv2.moments(nhood[:, :2])).flatten()
        yz_hu_moments = cv2.HuMoments(cv2.moments(nhood[:, 1:])).flatten()
        xz_hu_moments = cv2.HuMoments(cv2.moments(nhood[:, ::2])).flatten()
        hu_moments = np.concatenate([xy_hu_moments, yz_hu_moments, xz_hu_moments])
        normal = get_normal(x, y, grid_x, grid_y, grid_z)
        if normal == "None": # array comparision raises ambiguity error, so None passed as string
            continue
        final_keypoints.append(point)
        point_features.extend(np.array([x, y, z])) # spatial location
        point_features.extend(normal)
        point_features.extend(hu_moments)
        point_features = np.array(point_features)

        feature_list.append(point_features)
    final_keypoints = np.array(final_keypoints)
    return final_keypoints, feature_list


def get_features(edge_index):
    global features, keypoints
    edgewise_keypoint_features = [] # store features of keypoints for a given edge_index across all faces
    for face_index in range(1, len(file_paths)+1):
        try:
            edge_keypoints = keypoints["edge" + str(edge_index)][face_index-1]
            final_keypoints, keypoint_features = get_keypoint_features(edge_keypoints, face_index)
            keypoints["edge" + str(edge_index)][face_index-1] = final_keypoints # update the keypoint, remove unwanted keypoints like those on the edge etc
        except: # for no keypoints, no features
            keypoint_features = []
        edgewise_keypoint_features.append(keypoint_features)
    features["edge" + str(edge_index)] = edgewise_keypoint_features



def update_features(keypoints):
    threads = []
    for edge_index in range(1, len(keypoints)+1):
        thread = threading.Thread(target=get_features, args=(edge_index, ))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()


def get_keypoint_under_2rho(keypoints, point):
    """return the index of the keypoint in `keypoints` which is closest to `point` if that distance is less than 2 * rho, else return None"""
    try:
        distance = np.sqrt(np.sum(np.square(keypoints-point), axis=1))
        if (distance < 3*rho).any():
            min_dist_index = np.argmin(distance)
            return min_dist_index
    except Exception as e: # keypoints is [], gotta return None
        pass
    return None


def get_matching_keypoints(edge_keypoints, edge_features, edge_index):
    # check if a bunch of keypoints across the patches (across all faces) are withing 2*rho and their euclidean dist < Kq
    # first get all the keypoints in a list
    matching_keypoints_list = []
    for face_index1 in range(len(edge_keypoints)): # take a patch along the edge among the faces
        for point_index, point in enumerate(edge_keypoints[face_index1]): # take a keypoint in that patch, we have to find corresponding keypoints in each other patche along this edge
            matched_keypoint_indices = [] # to store indices of matched keypoints across the patches
            for face_index2 in range(len(edge_keypoints)): # find if matching keypoints exist across the patches along that edge across all faces
                if face_index2 == face_index1:
                    matched_keypoint_indices.append(point_index)
                    continue
                matched_keypoint = get_keypoint_under_2rho(edge_keypoints[face_index2], point)
                if matched_keypoint:
                    #if edge_index == 36: pdb.set_trace()I#
                    matched_keypoint_indices.append(matched_keypoint)
                else: # no keypoint was matched in the above patch (face_index2), gotta start search on other keypoint from face_index1
                    break

            if len(matched_keypoint_indices) == len(edge_keypoints): # there's a corresponding keypoint for each patch across all faces
                 matching_keypoints_list.append(matched_keypoint_indices)
    if len(matching_keypoints_list) == 0:
        return []
    # now we have those keypoints which are in vicinity of 2*rho, let's compute euclidean distance of their feature vectors
    final_matched_keypoints = []
    for matched_keypoints in matching_keypoints_list: # select first list of matching keypoints
        # get the indices, get their corresponding features, compute euclidean distance
        try:
            features = np.array([edge_features[face_index][idx] for face_index, idx in zip(range(len(edge_features)), matched_keypoints)])
            euc_dist_under_kq = lambda feature, features: np.sqrt(np.sum(np.square(features - feature), axis=1)) < Kq
            if np.apply_along_axis(euc_dist_under_kq, 1, features, features).all() == True:
                # we have got a set of matching keypoints, get their mean coordinates
                matched_coords = [edge_keypoints[face_index][idx] for face_index, idx in zip(range(len(edge_features)), matched_keypoints)]
                final_matched_keypoints.append(np.mean(matched_coords, axis=0))
        except:
            pdb.set_trace()
    return final_matched_keypoints


def keypoint_matching_thread(edge_index):
    global new_keypoints, edge_keypoints, edge_features
    edge_keypoints = keypoints["edge" + str(edge_index)]
    edge_features = features["edge" + str(edge_index)]
    matched_keypoints = get_matching_keypoints(edge_keypoints, edge_features, edge_index)
    if len(matched_keypoints):
        new_keypoints.extend(matched_keypoints)




# those keypoints which are in vicinity of 2*rho are considered for matching
# matching is done using constrained nearest neighbour
# choose an edge, select a keypoint, find out keypoints on corresponding patches on other faces within a vicinity of 2*rho,
# get euclidean distance in features among all possible pair wise combinations, if the distances come out to be less than Kp are added to the global set of correspondences
def keypoint_matching(keypoints, features):
    thread = []
    for edge_index in range(1, len(keypoints)+1):
        thread = threading.Thread(target=keypoint_matching_thread, args=(edge_index, ))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()


global face_points, grid_data, patches, keypoints, features, new_keypoints

face_points = {}
grid_data = {}
num_iterations = 10
patches = defaultdict(list) # key = edges, values = a list of extracted patches from all faces along that edge
keypoints = {} # key = edge, value = a list of keypoints extracted from the patches along that edge across all faces
features = {} # key = edge + edge_index, value = list of features for each keypoint across all the faces

# THRESHOLDS
rho = 0.5
eigen_ratio_threshold = 5000
Kq = 10

file_paths = {
    "path1": "F0001/F0001_AN01WH_F3D.wrl",
    "path2": "F0001/F0001_AN02WH_F3D.wrl",
    "path3": "F0001/F0001_AN03WH_F3D.wrl",
    "path4": "F0001/F0001_AN04WH_F3D.wrl",
    "path5": "F0001/F0001_DI01WH_F3D.wrl",
    "path6": "F0001/F0001_DI02WH_F3D.wrl",
    "path7": "F0001/F0001_DI03WH_F3D.wrl",
    "path8": "F0001/F0001_DI04WH_F3D.wrl",

}

for i in range(1,len(file_paths)+1):
    threads = []
    thread = threading.Thread(target=get_data,args=(file_paths["path"+str(i)],"face"+str(i)))
    thread.start()
    threads.append(thread)
for thread in threads:
    thread.join()


hull = np.zeros([73, 3])
for i in range(1, len(file_paths)+1):
    hull += get_hull(face_points["face" + str(i)])
hull = hull / len(file_paths)

correspondence_set = hull

# Start correspondence densification loop
for iteration in range(num_iterations):
    new_keypoints = []
    print("\n\nStarting iteration: ", iteration)
    t1 = time.time()
    print("Starting Delaunay triangulation............", end="", flush=True)
    tri_hull = triangulation(correspondence_set)
    print("Done | time taken: %0.4f seconds" % (time.time() - t1))

    t2 = time.time()
    print("Starting geodesic patch extraction............", end="", flush=True)
    update_patches(correspondence_set, tri_hull.simplices)
    print("Done | time taken: %0.4f seconds" % (time.time() - t2))

    t3 = time.time()
    print("Starting keypoint extraction............", end="", flush=True)
    update_keypoints(patches)
    print("Done | time taken: %0.4f seconds" % (time.time() - t3))

    t4 = time.time()
    print("Starting feature extraction............", end="", flush=True)
    update_features(keypoints)
    print("Done | time taken: %0.4f seconds" % (time.time() - t4))

    t5 = time.time()
    print("Starting keypoint matching............", end="", flush=True)
    keypoint_matching(keypoints, features)
    print("Done | time taken: %0.4f seconds" % (time.time() - t5))

    if len(new_keypoints) == 0:
        print("No new keypoints found")
        break

    new_keypoints = np.unique(np.array(new_keypoints), axis=0)
    print("Total new correspondences found: ", len(new_keypoints))
    print("Updating correspondence set...")
    correspondence_set = np.concatenate((correspondence_set, new_keypoints), axis=0)
    print("Iteration completed in %0.4f seconds" % (time.time() - t1))




