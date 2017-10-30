from ij import IJ, ImagePlus, VirtualStack, Menus
from ij.process import ImageConverter, AutoThresholder, ImageProcessor
from ij.measure import ResultsTable
from ij.plugin import ChannelSplitter, RGBStackMerge
from ij.plugin.frame import RoiManager
from ij.plugin.filter import ParticleAnalyzer
from ij.measure import Measurements
from ij.gui import Roi

from java.lang import Double
from java.awt import Color

import os, glob, re


#
# Stackoverflow code for numerically sorting strings
# https://stackoverflow.com/questions/4623446/how-do-you-sort-files-numerically
#
def tryint(s):
    try:
        return int(s)
    except:
        return s

def alphanum_key(s):
    """ Turn a string into a list of string and number chunks.
        "z23a" -> ["z", 23, "a"]
    """
    return [ tryint(c) for c in re.split('([0-9]+)', s) ]

def sort_nicely(l):
    """ Sort the given list in the way that humans expect.
    """
    l.sort(key=alphanum_key)
    
#
#
#
    

# Input Params
# TODO: should find a way to input besides hardcoding
datasetName = 'A10'
inputDir = '/home/nwalczak/workspace/elm/tmp/A10'
outputDir = '/home/nwalczak/workspace/elm/tmp/test_output'
numChannels = 4;
numZ = 1;
noZInFile = True;

chanLabel = ['skip', 'brightfield', 'yellow', 'blue'];

# Get currently selected image
#imp = WindowManager.getCurrentImage()
#imp = IJ.openImage('http://fiji.sc/samples/FakeTracks.tif')
#fo = FolderOpener()


imgFiles = glob.glob(os.path.join(inputDir, "*.tif"))
# Ensure we have tifs
if (len(imgFiles) < 1):
    print "No tif files found in input directory!  Input dir: " + inputDir
    quit()

sort_nicely(imgFiles)
# Get info about image dimensions - needed for creating stacks
firstImage = IJ.openImage(imgFiles[0]);
imgWidth = firstImage.getWidth();
imgHeight = firstImage.getHeight();

# Count how many images we have for each channel/Z slice
imgFileCats = [[[] for z in range(numZ)] for c in range(numChannels)]
for c in range(0, numChannels):
    chanStr = 'ch%(channel)02d' % {"channel" : c + 1};
    for z in range(0, numZ):
        zStr =  'z%(depth)02d' % {"depth" : z};
        count = 0;
        for imgPath in imgFiles:
            fileName = os.path.basename(imgPath)
            if chanStr in fileName and (noZInFile or zStr in fileName):
                imgFileCats[c][z].append(fileName)

# Load all images
currZ = 0;images = [[0 for z in range(numZ)] for c in range(numChannels)]
for c in range(0, numChannels):
    for z in range(0, numZ):
        imSeq = VirtualStack(imgWidth, imgHeight, firstImage.getProcessor().getColorModel(), inputDir)
        for fileName in imgFileCats[c][z]:
            imSeq.addSlice(fileName);
        images[c][z] = ImagePlus()
        images[c][z].setStack(imSeq)
        images[c][z].setTitle(datasetName + ", channel " + str(c) + ", z " + str(z))

# Process images
thresholder = AutoThresholder();
# We need to avoid the scale bar in the bottom of the image, so set a roi that doesn't include it
analysisRoi = Roi(0,0,512,480)
areas = []
for c in range(0, numChannels):
    chanStr = 'ch%(channel)02d' % {"channel" : c + 1};
    for z in range(0, numZ):
        zStr =  'z%(depth)02d' % {"depth" : z};
        currIP = images[c][z];
        currIP.show()
        # We need to get to a grayscale image, which will be done differently for different channels
        if (chanLabel[c] == "brightfield"):
            toGray = ImageConverter(currIP)
            toGray.convertToGray8()
            minCircularity = 0.1 # We want to identify one big cell ball, so ignore small less circular objects
            minSize = 40
        elif (chanLabel[c] == "blue"): # 
            imgChanns = ChannelSplitter.split(currIP);
            currIp = imgChanns[2];
            minCircularity = 0.02
            minSize = 5
        elif (chanLabel[c] == "yellow"):
            title = currIP.getTitle()
            imgChanns = ChannelSplitter.split(currIP);
            RGBStackMerge.mergeStacks(imgChanns[0].getImageStack(), imgChanns[1].getImageStack(), None, True)
            currIp = imgChanns[1];
            minCircularity = 0.02
            minSize = 5
        elif (chanLabel[c] == "skip"):
            continue 
        currIP.show()
        currIP.getProcessor().setAutoThreshold("Default", False, ImageProcessor.NO_LUT_UPDATE)
        IJ.run(currIP, "Convert to Mask", "")
        IJ.run(currIP, "Close-", "")
        currIP.show()
        currIP.setRoi(analysisRoi)
        
        # Create a table to store the results
        table = ResultsTable()
        # Create a hidden ROI manager, to store a ROI for each blob or cell
        roim = RoiManager(True)
        # Create a ParticleAnalyzer, with arguments:
        # 1. options (could be SHOW_ROI_MASKS, SHOW_OUTLINES, SHOW_MASKS, SHOW_NONE, ADD_TO_MANAGER, and others; combined with bitwise-or)
        # 2. measurement options (see [http://imagej.net/developer/api/ij/measure/Measurements.html Measurements])
        # 3. a ResultsTable to store the measurements
        # 4. The minimum size of a particle to consider for measurement
        # 5. The maximum size (idem)
        # 6. The minimum circularity of a particle
        # 7. The maximum circularity
        paFlags = ParticleAnalyzer.IN_SITU_SHOW | ParticleAnalyzer.SHOW_OUTLINES | ParticleAnalyzer.ADD_TO_MANAGER | ParticleAnalyzer.EXCLUDE_EDGE_PARTICLES | ParticleAnalyzer.SHOW_ROI_MASKS
        pa = ParticleAnalyzer(paFlags, Measurements.AREA, table, minSize, Double.POSITIVE_INFINITY, minCircularity, 1.0)
        #pa.setHideOutputImage(True)

        if pa.analyze(currIP):
            print "All ok"
        else:
            print "There was a problem in analyzing", currIP

        for i in range(0, roim.getCount()) :
            r = roim.getRoi(i);
            r.setColor(Color.red)
            r.setStrokeWidth(2)
        
        outImg = pa.getOutputImage()
        IJ.saveAs('png', os.path.join(outputDir, "Segmentation_" + datasetName + "_" + zStr + "_" + chanStr + "_particles.png"))

        # The measured areas are listed in the first column of the results table, as a float array:
        areas.append(table.getColumn(0))
    
resultsFile = open(os.path.join(outputDir, datasetName + "results.txt"), "w")
resultsFile.write("frame, brightfield area, yellow area, blue area, percent yellow, percent blue, classification \n")
for c in range(0, numChannels) :
    area = 0;
    if (chanLabel[c] == "brightfield"):
        area = max(areas[c])
        totalArea = area
    elif (chanLabel[c] == "blue"): # 
        area = sum(areas[c])
        blueArea = area
    elif (chanLabel[c] == "yellow"):
        area = sum(areas[c])
        yellowArea = area
    elif (chanLabel[c] == "skip"):
        continue 
percentBlue = blueArea / totalArea
percentYellow = yellowArea / totalArea
resultsFile.write("%d, %d, %d, %d, %0.4f, %0.4f \n" % (1, totalArea, yellowArea, blueArea, percentYellow, percentBlue))
resultsFile.close()

cmds = Menus.getCommands()
tmp = 5;

        
        