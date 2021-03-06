/*
  Copyright (C) 2011 - 2019, Raytheon BBN Technologies and contributors listed
  in the AUTHORS file in TASBE Flow Analytics distribution's top directory.

  This file is part of the TASBE Flow Analytics package, and is distributed
  under the terms of the GNU General Public License, with a linking
  exception, as described in the file LICENSE in the TASBE Image Analysis
  package distribution's top directory.
*/

#include <iostream>
#include <fstream>
#include <stdio.h>
#include <sstream>
#include <string>
#include <algorithm>

#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl/io/ply_io.h>
#include <pcl/filters/voxel_grid.h>
#include <pcl/filters/filter.h>
#include <pcl/common/time.h>
#include <pcl/common/impl/common.hpp>

#include <pcl/ModelCoefficients.h>
#include <pcl/filters/extract_indices.h>
#include <pcl/kdtree/kdtree.h>
#include <pcl/sample_consensus/method_types.h>
#include <pcl/sample_consensus/model_types.h>

#include <pcl/segmentation/sac_segmentation.h>
#include <pcl/segmentation/extract_clusters.h>
#include <pcl/segmentation/impl/extract_clusters.hpp>
#include <pcl/segmentation/cpc_segmentation.h>
#include <pcl/segmentation/impl/cpc_segmentation.hpp>

#include <opencv2/core.hpp>
#include <opencv2/highgui.hpp>
#include <opencv2/imgproc.hpp>

#include <boost/filesystem.hpp>

#include "../../../include/core/SegParams.h"
#include "core/MicroscopeProperties.h"

using namespace std;
using namespace pcl;
using namespace cv;

namespace fs = boost::filesystem;

typedef pcl::PointXYZRGB PointT;
typedef pcl::PointCloud<PointT> Cloud;
typedef Cloud::Ptr CloudPtr;
typedef pcl::LCCPSegmentation<PointT>::SupervoxelAdjacencyList SuperVoxelAdjacencyList;

typedef pcl::PointCloud<PointNormal> PointCloudWithNormals;

void printUsage() {
	cout << "This program performs segmentation on a 3D point " << endl
			<< "cloud. It takes one parameter, a path to a " << endl
			<< "configuration ini file."
			<< endl << endl
			<< "Usage: " << endl
			<< "<pathToIni>"
			<< endl << endl
			<< SegParams::getDescription()
			<< endl;
}

/**
 *
 */
std::vector<PointIndices> segment(CloudPtr cloud,
		SegParams & segParams) {

	// Creating the KdTree object for the search method of the extraction
	search::KdTree<PointT>::Ptr tree(new search::KdTree<PointT>);
	tree->setInputCloud(cloud);

	std::vector<PointIndices> cluster_indices;

	string outPath = segParams.getValue(SegParams::OUTPUT_DIR);
	string runName;
	if (segParams.hasParam(SegParams::RUN_NAME)) {
		runName = segParams.getValue(SegParams::RUN_NAME);
	}

	if (!segParams.hasParam(SegParams::SEG_TYPE)
			|| segParams.getValue(SegParams::SEG_TYPE)
					== SegParams::ST_EUCLIDEAN) {

		EuclideanClusterExtraction<PointT> ec;
		if (segParams.hasParam(SegParams::EUC_CLUSTER_TOLERANCE)) {
			ec.setClusterTolerance(
					segParams.getDouble(SegParams::EUC_CLUSTER_TOLERANCE));
		} else {
			ec.setClusterTolerance(10);
		}
		if (segParams.hasParam(SegParams::MIN_CLUSTER_SIZE)) {
			ec.setMinClusterSize(
					segParams.getDouble(SegParams::MIN_CLUSTER_SIZE));
		} else {
			ec.setMinClusterSize(5);
		}
		if (segParams.hasParam(SegParams::MAX_CLUSTER_SIZE)) {
			ec.setMaxClusterSize(
					segParams.getDouble(SegParams::MAX_CLUSTER_SIZE));
		}

		ec.setSearchMethod(tree);
		ec.setInputCloud(cloud);
		ec.extract(cluster_indices);
	} else if (segParams.getValue(SegParams::SEG_TYPE) == SegParams::ST_VOXEL) {
		// Supervoxel Stuff
		float voxelResolution = 10.0f;
		float seedResolution = 20.0f;
		float colorImportance = 0.0f;
		float spatialImportance = 1.0f;
		float normalImportance = 1.0f;
		bool useSingleCamTransform = false;
		bool useSupervoxelRefinement = false;

		// LCCPSegmentation Stuff
		float concavityToleranceThreshold = 10;
		float smoothnessThreshold = 0.1;
		uint32_t minSegmentSize = 0;
		bool useExtendedConvexity = false;
		bool useSanityCriterion = false;

		// CPCSegmentation Stuff
		float minCutScore = 0.16;
		unsigned int maxCuts = 25;
		unsigned int cuttingMinSegments = 400;
		bool useLocalConstrain = true;
		bool useDirectedCutting = true;
		bool useCleanCutting = true;
		unsigned int ransacIterations = 10000;

		unsigned int kFactor = 0;
		if (useExtendedConvexity) {
			kFactor = 1;
		}

		// Don't display info messages, to avoid output from SuperVoxel
		pcl::console::setVerbosityLevel(console::VERBOSITY_LEVEL::L_ERROR);

		cout << "\tCreating Supervoxels" << endl;
		SupervoxelClustering<PointT> super(voxelResolution, seedResolution);
		super.setUseSingleCameraTransform(useSingleCamTransform);
		super.setInputCloud(cloud);
		super.setColorImportance(colorImportance);
		super.setSpatialImportance(spatialImportance);
		super.setNormalImportance(normalImportance);
		map<uint32_t, Supervoxel<PointT>::Ptr> supervoxelClusters;
		super.extract(supervoxelClusters);

		if (useSupervoxelRefinement) {
			cout << "\tRefining supervoxels" << endl;
			super.refineSupervoxels(2, supervoxelClusters);
		}
		cout << "\tNum Supervoxels: " << supervoxelClusters.size() << endl;

		multimap<uint32_t, uint32_t> supervoxelAdjacency;
		super.getSupervoxelAdjacency(supervoxelAdjacency);

		/// The Main Step: Perform LCCPSegmentation
		cout << "\tStarting Segmentation" << endl;
		CPCSegmentation<PointT> cpc;
		cpc.setConcavityToleranceThreshold(concavityToleranceThreshold);
		cpc.setSanityCheck(useSanityCriterion);
		cpc.setSmoothnessCheck(true, voxelResolution, seedResolution,
				smoothnessThreshold);
		cpc.setCutting(maxCuts, cuttingMinSegments, minCutScore,
				useLocalConstrain, useDirectedCutting, useCleanCutting);
		cpc.setRANSACIterations(ransacIterations);
		cpc.setKFactor(kFactor);
		cpc.setInputSupervoxels(supervoxelClusters, supervoxelAdjacency);
		cpc.setMinSegmentSize(minSegmentSize);
		cpc.segment();

		cout << "\tInterpolation voxel cloud -> input cloud and relabeling" << endl;
		PointCloud<PointXYZL>::Ptr svxLblCld = super.getLabeledCloud();
		PointCloud<PointXYZL>::Ptr lccpLblCld = svxLblCld->makeShared();
		cpc.relabelCloud(*lccpLblCld);

		// Relabel Supervoxel IDs
		vector<uint32_t> svxIds;
		for (auto & it : supervoxelClusters) {
			svxIds.push_back(it.first);
		}
		std::random_shuffle(svxIds.rbegin(), svxIds.rend());
		map<uint32_t, uint32_t> svxRemap;
		for (int i = 1; i <= svxIds.size(); i++) {
			svxRemap[svxIds[i - 1]] = i;
		}
		for (int i = 0; i < svxLblCld->size(); i++) {
			PointXYZL & pt = svxLblCld->points[i];
			pt.label = svxRemap[pt.label];
		}
		// Relabel Cluster Ids
		set<uint32_t> idSet;
		for (int i = 0; i < lccpLblCld->size(); i++) {
			idSet.insert(lccpLblCld->points[i].label);
		}
		vector<uint32_t> clusterIds(idSet.begin(), idSet.end());
		std::random_shuffle(clusterIds.rbegin(), clusterIds.rend());
		map<uint32_t, uint32_t> clusterRemap;
		int currId = 1;
		for (auto & it : clusterIds) {
			clusterRemap[it] = currId;
			currId++;
		}
		for (int i = 0; i < lccpLblCld->size(); i++) {
			PointXYZL & pt = lccpLblCld->points[i];
			pt.label = clusterRemap[pt.label];
		}

		if (segParams.hasParam(SegParams::DEBUG)) {
			std::stringstream ss;
			ss << outPath << "/" << runName << "_debug_svCloud.ply";
			io::savePLYFile(ss.str(), *svxLblCld, false);
			ss.str(""); ss.clear();
			ss << outPath << "/" << runName << "_debug_clusterCloud.ply";
			io::savePLYFile(ss.str(), *lccpLblCld, false);
		}

		map<uint32_t, PointIndices> ptIdxMap;
		for (int i = 0; i < lccpLblCld->size(); i++) {
			const PointXYZL & pt = lccpLblCld->points[i];
			ptIdxMap[pt.label].indices.push_back(i);
		}
		for (auto &it : ptIdxMap) {
			if (it.second.indices.size() > 5) {
				cluster_indices.push_back(it.second);
			}
		}

	} else {
		cout << "Unknown segmentation type: "
				<< segParams.getValue(SegParams::SEG_TYPE) << endl;
		cout << "Accepted segmentation types: " << endl;
		cout << SegParams::ST_EUCLIDEAN << endl;
		cout << SegParams::ST_VOXEL << endl;
	}

	return cluster_indices;
}

/**
 * From https://stackoverflow.com/questions/20446201/how-to-check-if-string-ends-with-txt/20446257
 */
bool has_suffix(const std::string &str, const std::string &suffix)
{
    return str.size() >= suffix.size() &&
           str.compare(str.size() - suffix.size(), suffix.size(), suffix) == 0;
}

/**
 *
 */
int main(const int argc, const char **argv) {
	if (argc != 2) {
		cout << "Expected 1 inputs, received " << (argc - 1) << endl << endl;
		printUsage();
		return 0;
	}

	SegParams segParams;
	if (!segParams.loadParameters(argv[1])) {
		cout << "Failed loading segmentation parameters!" << endl;
		return 0;
	}
	cout << segParams << endl;

	if (!segParams.hasParam(SegParams::INPUT_CLOUD)) {
		cout << "Input cloud not specified!" << endl;
		printUsage();
		return 0;
	}
	if (!segParams.hasParam(SegParams::OUTPUT_DIR)) {
		cout << "Output dir not specified!" << endl;
		printUsage();
		return 0;
	}
	if (!segParams.hasParam(SegParams::SCOPE_PROPERTIES)) {
		cout << "Microscope properties not specified!" << endl;
		printUsage();
		return 0;
	}

	string inFile = segParams.getValue(SegParams::INPUT_CLOUD);
	string outPath = segParams.getValue(SegParams::OUTPUT_DIR);
	string runName;
	if (segParams.hasParam(SegParams::RUN_NAME)) {
		runName = segParams.getValue(SegParams::RUN_NAME);
	}

	// Ensure output dir exists
	fs::path boostOutPath(outPath);
	if (!fs::exists(boostOutPath)) {
		fs::create_directory(boostOutPath);
	}

	MicroscopeProperties scopeProps;
	string scopePropsFile = segParams.getValue(SegParams::SCOPE_PROPERTIES);
	if (has_suffix(scopePropsFile, ".ini")) {
		if (!scopeProps.readFromINI(scopePropsFile)) {
			cout << "Failed loading microscope ini properties! File: "
					<< scopePropsFile << endl;
			return 0;
		}
	} else {
		if (!scopeProps.readFromXML(scopePropsFile)) {
			cout << "Failed loading microscope xml properties! File: "
					<< scopePropsFile << endl;
			return 0;
		}
	}

	cout << scopeProps << endl;

	CloudPtr cloud(new Cloud);
	io::loadPLYFile (inFile.c_str(), *cloud);

	cout << "Num input points: " << cloud->size() << endl;

	PointT minVals, maxVals;
	getMinMax3D(*cloud, minVals, maxVals);
	cout << "Min Vals: " << minVals << endl;
	cout << "Max Vals: " << maxVals << endl;
	int numCols = scopeProps.imageWidth;
	int numRows = scopeProps.imageHeight;

	cout << "Segmenting..." << endl;
	StopWatch time;
	std::vector<PointIndices> clusterIndices = segment(cloud, segParams);
	double runTime = time.getTime();

	int numClusters = clusterIndices.size();
	int currCluster = 1;
	double maskScale = 255.0 / numClusters;
	cout << "\tSegmented cloud in " << runTime << "ms!" << endl;
	cout << "\tNum clusters: " << numClusters << endl;
	Mat segImage(numRows, numCols, CV_8UC1, Scalar(0));
	PointCloud<PointXYZRGBL> clusterCloud;
	std::stringstream ss;
	ss << outPath << "/" << runName << "_clusterStats" << ".csv";
	std::ofstream clusterStats;
	clusterStats.open(ss.str().c_str());
	clusterStats << "clusterId, numPoints, volume, "
			"integrated red, integrated green, integrated blue, "
			"avg red, avg green, avg blue, " << endl;
	double ptVolume = scopeProps.pixelWidth * scopeProps.pixelHeight
			* scopeProps.pixelDepth;
	struct ClusterStat{
		int clusterId;
		int size;
		ClusterStat(int id, int size) : clusterId(id), size(size) {}
	};
	vector<ClusterStat> clusterSizes;
	for (auto it = clusterIndices.begin(); it != clusterIndices.end(); ++it) {
		int totalRed, totalGreen, totalBlue;
		totalRed = totalGreen = totalBlue = 0;
		for (auto pit = it->indices.begin(); pit != it->indices.end(); ++pit) {
			PointT & pt = cloud->points[*pit];
			PointXYZRGBL ptl(pt.r, pt.g, pt.b, currCluster);
			ptl.x = pt.x; ptl.y = pt.y; ptl.z = pt.z;
			totalRed += pt.r; totalGreen += pt.g; totalBlue += pt.b;
			clusterCloud.push_back(ptl);
			int col = (int)(pt.x / scopeProps.pixelWidth);
			int row = (int)(pt.y / scopeProps.pixelHeight);
			segImage.at<uchar>(row, col) = (uchar)(currCluster * maskScale);
		}
		int numPoints = it->indices.size();
		clusterStats << currCluster << ", " << numPoints << ", "
				<< numPoints * ptVolume << ", " << totalRed << ", "
				<< totalGreen << ", " << totalBlue << ", "
				<< totalRed / numPoints << ", " << totalGreen / numPoints
				<< ", " << totalBlue / numPoints << endl;
		clusterSizes.push_back(ClusterStat(currCluster, numPoints));

		currCluster++;
	}
	clusterStats.close();

	std::sort(clusterSizes.rbegin(), clusterSizes.rend(),
			[] (const ClusterStat &a, const ClusterStat &b) {
				return (a.size < b.size);
			});
	cout << "Top 10 largest clusters: " << endl;
	for (int i = 0; i < clusterSizes.size() && i < 10; i++) {
		cout << "\t\tCluster " << setw(5) << right << clusterSizes[i].clusterId
				<< ", num pts: " << clusterSizes[i].size << endl;
	}

	// Save cloud of labeled points
	ss.str(""); ss.clear();
	ss << outPath << "/" << runName << "_clusters" << ".ply";
	io::savePLYFile(ss.str(), clusterCloud, false);

	// Save 2D projection of segments
	Mat colorClusterMap;
	applyColorMap(segImage, colorClusterMap, COLORMAP_JET);
	for (int r = 0; r < segImage.rows; r++) {
		for (int c = 0; c < segImage.cols; c++) {
			if (segImage.at<uchar>(r,c) == 0) {
				colorClusterMap.at<Vec3b>(r,c) = Vec3b(0,0,0);
			}
		}
	}

	ss.str(""); ss.clear();
	ss << outPath << "/" << runName << "_segMask.png";
	imwrite(ss.str(), colorClusterMap);

	cout << endl << "Done!" << endl;
}




