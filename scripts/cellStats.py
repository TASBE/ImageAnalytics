from ij import IJ, ImagePlus, VirtualStack, WindowManager
from ij.process import ImageConverter, ImageProcessor, ByteProcessor
from ij.measure import ResultsTable
from ij.plugin import ChannelSplitter
#from ij.plugin.frame import RoiManager
from ij.plugin.filter import ParticleAnalyzer
from ij.measure import Measurements
from ij.gui import Roi

from java.lang import Double
import os, glob, re, time, sys
import ConfigParser
import xml.etree.ElementTree as ElementTree
#from jarray import zeros

#Recognized colors
RED = "Red"
GREEN = "Green"
BLUE = "Blue"
YELLOW = "Yellow"
BRIGHTFIELD = "Gray"
SKIP = "Skip"

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
def printUsage():
    global numChannels;
    global numZ;
    
    print "This script will read tif files from an input directory and compute statistics on the cell images."
    print "The script must be pointed to a configuration ini file that will define several important aspects."
    print "The input and output dirs must be defined in the config file, however all of the rest of the config"
    print " can be read in from the microscope properties if they exist in the Metadata dir in the input."
    print "The following parameters are recognized in the [Config] section:"

    print "inputDir  - Dir to read in tif files from. (Required)"
    print "outputDir - Dir to write output to. (Required)"
    print "numChannels - Number of channels in dataset, defaults to 4, also read from XML properties"
    print "numZ - Number of Z slices in dataset, defaults to 1, also read from XML properties"
    print "noZInFile - True if the z slice does not appear in the filename, otherwise false, also read from XML properties"
    print "chanLabel - Label that describes source for each channel, default skip, yellow, blue, brightfield, also read from XML properties"
    print "            Valid labels: skip, brightfield, red, green, blue, yellow"
    print "chansToSkip - List of channel names that will be skipped if channels are read from XML properties"
    print "analysisRoi - Rectangular area to perform cell detection on, default 0,0,512,480, must be defined in config file"
    print "dsNameIdx - Index of well name within filename, when delimiting on underscores (_), also read from XML properties"
    print "wellNames - Optional, list of well names to process, others are ignored"
    print "debugOutput - Optional, True or False, if True output additional info for debugging purposes"

    print "Usage: "
    print "<cfgPath>"
 
 
####
#
#
####
def getCSVHeader(cfg):
    outputChans = [];
    for chan in cfg.chanLabel:
        if not chan == SKIP and not chan == BRIGHTFIELD:
            outputChans.append(chan)
    headerString = "frame, brightfield area (um^2), "
    for chan in outputChans:
        headerString += chan + " area (um^2), "
        headerString += "percent " + chan + ", " 
    headerString += "classification \n"
    return headerString

####
#
#
####
def main(cfg):
    # Input Params
    # TODO: should find a way to input besides hardcoding

    print "Processing input dir " + cfg.inputDir;
    print "Outputting in " + cfg.outputDir;

    # Get all images in the input dir
    imgFiles = glob.glob(os.path.join(cfg.inputDir, "*.tif"))
    # Ensure we have tifs
    if (len(imgFiles) < 1):
        print "No tif files found in input directory!  Input dir: " + cfg.inputDir
        quit()

    # Sort filenames so they are in order by z and ch
    sort_nicely(imgFiles)

    # Get the names of all wells that exist in this dataset/plate
    wellNames = []
    # Each well will have a collection of images, but will all fall under the same common prefix descriptor
    # Such as: plate1_Aug284pm_A1_S001
    wellDesc = dict()
    noZInFile = dict()
    # Analyze image filenames to get different pieces of information
    # We care about a time, Z, channel, and the well name
    timeRE = re.compile("^t[0-9]+$")
    zRE    = re.compile("z[0-9]+$")
    chRE   = re.compile("^ch[0-9]+$")
    wellRE   = re.compile("^[A-Z][0-9]+$")
    for filePath in imgFiles:
        fileName = os.path.basename(filePath)
        toks = os.path.splitext(fileName)[0].split("_")
        # Parse file name to get indices of certain values
        tIdx = zIdx = chIdx = sys.maxint
        wellIndex = sys.maxint # This will be the lowest index that matches the well expression
        for i in range(0, len(toks)):
            if timeRE.match(toks[i]):
                tIdx = i
            if zRE.match(toks[i]):
                zIdx = i
            if chRE.match(toks[i]):
                chIdx = i
            if wellRE.match(toks[i]) and i < wellIndex:
                wellIndex = i
        
        minInfoIdx = min(tIdx, min(zIdx, chIdx))
        wellNames.append(toks[wellIndex])
        wellDesc[toks[wellIndex]] = fileName[0:fileName.find(toks[minInfoIdx]) - 1]
        noZInFile[toks[wellIndex]] = zIdx == -1        

    uniqueNames = list(set(wellNames))
    sort_nicely(uniqueNames)

    # Try to determine pixel size from Leica properties
    metadataDir = os.path.join(cfg.inputDir, "MetaData")
    metadataExists = True
    if not os.path.exists(metadataDir):
        print "No MetaData directory in input dir! Can't read properties!"
        metadataExists = False;

    # Process each well
    dsResults = []
    for wellName in uniqueNames:
        # Check to see if we should ignore this well
        if cfg.wellNames:
            if not wellName in cfg.wellNames:
                continue;

        dsImgFiles = [];
        for i in range(0, len(imgFiles)) :
            if wellName == wellNames[i] :
                dsImgFiles.append(imgFiles[i])
        # Make sure output dir exists for well
        wellPath = os.path.join(cfg.outputDir, wellName)
        if not os.path.exists(wellPath):
            os.makedirs(wellPath)

        # Update config based on metadata
        if (metadataExists):
            xmlFile = os.path.join(metadataDir, wellDesc[wellName] + "_Properties.xml")
            if not os.path.exists(xmlFile):
                print "No metadata XML file for well " + wellName + "! Skipping well.  Path: " + xmlFile
                continue;
            updateCfgWithXML(cfg, xmlFile)
            cfg.noZInFile = noZInFile[wellName] or cfg.numZ == 1

        cfg.printCfg()
        start = time.time()
        dsResults.append(wellName + ", " + processDataset(cfg, wellName, dsImgFiles))
        end = time.time()
        print("Processed well " + wellName + " in " + str(end - start) + " s")

    # Write out summary output
    resultsFile = open(os.path.join(cfg.outputDir, "AllResults.csv"), "w")

    resultsFile.write(getCSVHeader(cfg))
    for result in dsResults:
        resultsFile.write(result);
    resultsFile.close()    

####


####
#
# Given a path to a Leica properties XML, read in some configuration
#
####
def updateCfgWithXML(cfg, xmlFile):
    xmlRoot = ElementTree.parse(xmlFile).getroot()
    imgEle = xmlRoot.find("Image")
    imgDescEle = imgEle.find("ImageDescription")
    
    # Pull channel info from XML
    chanEle = imgDescEle.find("Channels")
    cfg.numChannels = len(chanEle.getchildren())
    chanNames = []
    for chan in chanEle.getchildren():
        newChan = chan.get("LUTName")
        if newChan in cfg.chansToSkip:
            chanNames.append(SKIP)
        else:
            chanNames.append(chan.get("LUTName"))
    cfg.chanLabel = chanNames
    
    # Pull dimension info from XML 
    dimsEle = imgDescEle.find("Dimensions")
    for dimEle in dimsEle.getchildren():
        numElementsInDim = int(dimEle.get("NumberOfElements"))
        dimLength = float(dimEle.get("Length"))
        dimUnit = dimEle.get("Unit")
        lenMultiplier = getMultiplier(dimUnit) # Ensures length is in micrometers
        if dimEle.get("DimID") == "X":
            cfg.pixelWidth = (dimLength * lenMultiplier) / numElementsInDim
        elif dimEle.get("DimID") == "Y":
            cfg.pixelHeight = (dimLength * lenMultiplier) / numElementsInDim
        elif dimEle.get("DimID") == "Z":
            cfg.numZ = numElementsInDim
#### 


####
#
# Get the multiplier to turn the given unit into micrometers
#
####
def getMultiplier(unit):
    mult = 1;
    if unit == "m":
        mult = 1e6;
    elif unit == "cm":
        mult = 1e4;
    elif unit == "mm":
        mult = 1e3;
    elif unit == "um":
        mult = 1;
    elif unit == "nm":
        mult = 1e-3;
    return mult;
####
#
#
####
def processDataset(cfg, datasetName, imgFiles):
    datasetPath = os.path.join(cfg.outputDir, datasetName)
    
    firstImage = IJ.openImage(imgFiles[0]);
    imgWidth = firstImage.getWidth();
    imgHeight = firstImage.getHeight();

    # Count how many images we have for each channel/Z slice
    imgFileCats = [[[] for z in range(cfg.numZ)] for c in range(cfg.numChannels)]
    addedImages = False
    for c in range(0, cfg.numChannels):
        chanStr = 'ch%(channel)02d' % {"channel" : c};
        for z in range(0, cfg.numZ):
            zStr =  'z%(depth)02d' % {"depth" : z};
            for imgPath in imgFiles:
                fileName = os.path.basename(imgPath)
                if chanStr in fileName and (cfg.noZInFile or zStr in fileName):
                    addedImages = True
                    imgFileCats[c][z].append(fileName)

    # Check for no images
    if not addedImages:
        print "Failed to add any images to chan/z categories! Problem with input dir?"
        quit()

    # Load all images
    images = [[0 for z in range(cfg.numZ)] for c in range(cfg.numChannels)]
    for c in range(0, cfg.numChannels):
        for z in range(0, cfg.numZ):
            if not imgFileCats[c][z]:
                continue;
            
            imSeq = VirtualStack(imgWidth, imgHeight, firstImage.getProcessor().getColorModel(), cfg.inputDir)
            for fileName in imgFileCats[c][z]:
                imSeq.addSlice(fileName);
            images[c][z] = ImagePlus()
            images[c][z].setStack(imSeq)
            images[c][z].setTitle(datasetName + ", channel " + str(c) + ", z " + str(z))
    
    # Process images
    areas = []
    processImages(cfg, datasetName, datasetPath, images, areas)

    # Output Results
    resultsFile = open(os.path.join(datasetPath, datasetName + "_results.txt"), "w")
    resultsFile.write(getCSVHeader(cfg));
    channelAreas = dict() 
    for c in range(0, cfg.numChannels) :
        chanStr = '_ch%(channel)02d_' % {"channel" : c};
        area = 0;
        writeArea = False
        # Handle brigthfield channel
        if (cfg.chanLabel[c] == BRIGHTFIELD):
            if not areas[c] :
                area = 0;
            else:
                area = max(areas[c])
                writeArea = True
            channelAreas["totalArea"] = area
        # Handle Fluorscent Channels   
        elif (cfg.chanLabel[c] == BLUE) or (cfg.chanLabel[c] == RED) or (cfg.chanLabel[c] == GREEN) or (cfg.chanLabel[c] == YELLOW): #
            if not areas[c] :
                area = 0;
            else:
                area = sum(areas[c]) 
                writeArea = True
            channelAreas[cfg.chanLabel[c]] = area
        # Skip channel
        elif (cfg.chanLabel[c] == SKIP):
            continue
        # Write out individual areas per channel
        if writeArea:
            chanResultsFile = open(os.path.join(datasetPath, datasetName + chanStr + "areas.txt"), "w")
            for a in areas[c] :
                chanResultsFile.write("%10.4f\n" % a)
            chanResultsFile.close()

    if channelAreas["totalArea"] == 0:
        channelAreas["totalArea"] = 0.000000001

    outputChans = [];
    for chan in cfg.chanLabel:
        if not chan == SKIP and not chan == BRIGHTFIELD:
            outputChans.append(chan)

    resultsString = "%d,\t\t\t %10.4f," % (1, channelAreas["totalArea"])
    for chan in outputChans:
        resultsString += "\t\t %10.4f," % channelAreas[chan]
        resultsString += "\t\t %0.4f," % (channelAreas[chan] /  channelAreas["totalArea"])
    resultsString += "\n"   
    resultsFile.write(resultsString)
    resultsFile.close()
    return resultsString

####
#
#  All of the processing that happens for each image
#
####
def processImages(cfg, wellName, wellPath, images, areas):
    for c in range(0, cfg.numChannels):
        chanStr = 'ch%(channel)02d' % {"channel" : c};
        for z in range(0, cfg.numZ):
            zStr =  'z%(depth)02d' % {"depth" : z};
            currIP = images[c][z];
            if cfg.debugOutput:
                WindowManager.setTempCurrentImage(currIP);
                IJ.saveAs('png', os.path.join(wellPath, "Orig_" + wellName + "_" + zStr + "_" + chanStr + ".png"))
            # We need to get to a grayscale image, which will be done differently for different channels
            if (cfg.chanLabel[c] == BRIGHTFIELD):
                toGray = ImageConverter(currIP)
                toGray.convertToGray8()
                minCircularity = 0.02 # We want to identify one big cell ball, so ignore small less circular objects
                minSize = 40
                darkBackground = False
            elif (cfg.chanLabel[c] == BLUE) or (cfg.chanLabel[c] == RED) or (cfg.chanLabel[c] == GREEN): #
                chanIdx = 2
                if (cfg.chanLabel[c] == RED):
                    chanIdx = 0
                elif (cfg.chanLabel[c] == GREEN):
                    chanIdx = 1;
                imgChanns = ChannelSplitter.split(currIP);
                currIP = imgChanns[chanIdx];
                minCircularity = 0.02
                minSize = 5
                darkBackground = True
            elif (cfg.chanLabel[c] == YELLOW):
                title = currIP.getTitle()
                # Create a new image that consists of the average of the red & green channels
                width = currIP.getWidth();
                height = currIP.getHeight();
                newPix = ByteProcessor(width, height)
                for x in range(0, width) :
                    for y in range(0,height) :
                        currPix = currIP.getPixel(x,y);
                        newPix.putPixel(x, y, (currPix[0] + currPix[1]) / 2)
                
                currIP = ImagePlus(title, newPix)
                minCircularity = 0.02
                minSize = 5
                darkBackground = True
            elif (cfg.chanLabel[c] == SKIP):
                areas.append([])
                continue
            WindowManager.setTempCurrentImage(currIP);
            if cfg.debugOutput:
                IJ.saveAs('png', os.path.join(wellPath, "Processing_" + wellName + "_" + zStr + "_" + chanStr + ".png"))
            currIP.getProcessor().setAutoThreshold("Default", darkBackground, ImageProcessor.NO_LUT_UPDATE)
            threshRange = currIP.getProcessor().getMaxThreshold() - currIP.getProcessor().getMinThreshold()
            print "\tChannel %14s threshold:\t [%d, %d]\t range: %d" % (cfg.chanLabel[c],currIP.getProcessor().getMinThreshold(), currIP.getProcessor().getMaxThreshold(), threshRange)
            if currIP.getType() != ImagePlus.GRAY8 :
                print "\tChannel " + cfg.chanLabel[c] + " is not GRAY8, instead type is %d" % currIP.getType()
            if threshRange > 230:
                print "\t\tIgnored Objects due to threshold range!"
                areas.append([])
                continue 
            IJ.run(currIP, "Convert to Mask", "")
            IJ.run(currIP, "Close-", "")
            if cfg.debugOutput:
                WindowManager.setTempCurrentImage(currIP);
                IJ.saveAs('png', os.path.join(wellPath, "Binary_" + wellName + "_" + zStr + "_" + chanStr + ".png"))
            currIP.setRoi(cfg.analysisRoi)
            
            # Create a table to store the results
            table = ResultsTable()
            # Create a hidden ROI manager, to store a ROI for each blob or cell
            #roim = RoiManager(True)
            # Create a ParticleAnalyzer
            paFlags = ParticleAnalyzer.IN_SITU_SHOW | ParticleAnalyzer.SHOW_OUTLINES | ParticleAnalyzer.SHOW_ROI_MASKS | ParticleAnalyzer.CLEAR_WORKSHEET
            pa = ParticleAnalyzer(paFlags, Measurements.AREA, table, minSize, Double.POSITIVE_INFINITY, minCircularity, 1.0)
            #pa.setHideOutputImage(True)
    
            if not pa.analyze(currIP):
                print "There was a problem in analyzing", currIP
    
            #for i in range(0, roim.getCount()) :
            #    r = roim.getRoi(i);
            #    r.setColor(Color.red)
            #    r.setStrokeWidth(2)
            
            #outImg = pa.getOutputImage()
            IJ.saveAs('png', os.path.join(wellPath, "Segmentation_" + wellName + "_" + zStr + "_" + chanStr + "_particles.png"))
    
            # The measured areas are listed in the first column of the results table, as a float array:
            newAreas = []
            if table.getColumn(0):
                for pixArea in table.getColumn(0):
                    newAreas.append(pixArea * cfg.pixelHeight * cfg.pixelWidth)
            areas.append(newAreas)
            #currIP.hide()


####
#
#  The Config Class - storing configuration info
#
####
class config:
    numChannels = 4;
    numZ = 1;
    noZInFile = True;
    chanLabel = [SKIP, YELLOW, BLUE, BRIGHTFIELD];
    chansToSkip = [];
    inputDir = '';
    outputDir = '';
    # We need to avoid the scale bar in the bottom of the image, so set a roi that doesn't include it
    #analysisRoi = Roi(0,0,512,480)
    analysisRoi = Roi(0,0,1024,980)
    # Determines what index the dataset name is within the tokenized filename
    dsNameIdx = 4;
    pixelHeight = 1; # in micrometers
    pixelWidth = 1; # in micrometers
    wellNames = [] # List of well names to process, empty implies process all
    debugOutput =  False; # If true, additional info will be output
    
    def printCfg(self):
        print("Using Config:")
        print("\tinputDir:\t"    + self.inputDir)
        print("\toutputDir:\t"   + self.outputDir)
        print("\twellNames:\t" + ", ".join(self.wellNames))
        print("\tnumChannels:\t" + str(self.numChannels))
        print("\tnumZ:\t\t"        + str(self.numZ))
        print("\tnoZInFile:\t"   + str(self.noZInFile))
        print("\tchanLabel:\t"   + ", ".join(self.chanLabel))
        print("\tanalysisRoi:\t" + str(self.analysisRoi))
        print("\tpixelHeight:\t" + str(self.pixelHeight))
        print("\tpixelWidth:\t" + str(self.pixelWidth))
        print("\tdebugOutput:\t" + str(self.debugOutput))
        print("\n")
####
#
#
####
    
    
####
#
#
####
# Checking for __main__ will cause running from ImageJ to fail        
#if __name__ == "__main__":

#@String cfgPath

# Check to see if cfgPath is defined
# They could be defined if running from ImageJ directly
try:
    cfgPath
except NameError:
    argc = len(sys.argv) - 1
    if not argc == 1:
        print "Expected 1 argument, received " + str(argc) + "!"
        printUsage()
        quit(1)
    cfgPath = sys.argv[1]

# Load the configuration file
cfgParser = ConfigParser.RawConfigParser(allow_no_value=True)
rv = cfgParser.readfp(open(cfgPath))

if not cfgParser.has_section("Config"):
    print "Config file doesn't contain [Config] section! Path: " + cfgPath;
    quit(1)

cfg = config()
if cfgParser.has_option("Config", "numchannels") :
    numChannels = int(cfgParser.get("Config", "numchannels"))
else:
    numChannels = cfg.numChannels
for option in cfgParser.options("Config"):
    if option == "inputdir":
        cfg.inputDir = cfgParser.get("Config", option)
    elif option == "outputdir":
        cfg.outputDir = cfgParser.get("Config", option)
    elif option == "numchannels":
        cfg.numChannels = int(cfgParser.get("Config", option))
    elif option == "numz":
        cfg.numZ = int(cfgParser.get("Config", option))
    elif option == "nozinfile":
        cfg.noZInFile  = bool(cfgParser.get("Config", option))
    elif option == "chanstoskip":
        toks = cfgParser.get("Config", option).split(",")
        cfg.chansToSkip = []
        for tok in toks:
            cfg.chansToSkip.append(tok.strip())
    elif option == "chanlabel":
        toks = cfgParser.get("Config", option).split(",")
        if not len(toks) == numChannels:
            print "Improper value for chanLabel config, expected " + numChannels + " comma separated values!  Received " + str(len(toks))
        cfg.chanLabel = []
        for tok in toks:
            cfg.chanLabel.append(tok.strip())
    elif option == "analysisroi":
        toks = cfgParser.get("Config", option).split(",")
        if not len(toks) == 4:
            print "Improper value for analysisRoi config, expected " + 4+ " comma separated values!  Received " + str(len(toks))
        cfg.analysisRoi = Roi(int(toks[0]),int(toks[1]),int(toks[2]),int(toks[3]))
    elif option == "dsnameidx":
        cfg.dsNameIdx = int(cfgParser.get("Config", option))
    elif option == "wellnames":
        toks = cfgParser.get("Config", option).split(",")
        for t in toks:
            cfg.wellNames.append(t)
    elif option == "debugoutput":
        cfg.debugOutput = bool(cfgParser.get("Config", option))
    else:
        print "Warning, unrecognized config option: " + option

# Print Config
print("Using Config:")
print("\tinputDir:\t"    + cfg.inputDir)
print("\toutputDir:\t"   + cfg.outputDir)
print("\twellNames:\t" + ", ".join(cfg.wellNames))
print("\tanalysisRoi:\t" + str(cfg.analysisRoi))
print("\tchansToSkip:\t" + ", ".join(cfg.chansToSkip))
print("\tdebugOutput:\t" + str(cfg.debugOutput))
print("\n")


    
start = time.time()
main(cfg)
end = time.time()
print("Processed all images in " + str(end - start) + " s")