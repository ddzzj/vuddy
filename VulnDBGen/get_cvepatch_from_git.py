#!/usr/bin/env python
"""
Created by Squizz on April 10, 2016
This script is for getting cve patches from git object.
Last modified: August 5, 2016

CHANGES
AUG 5   SB KIM  (*IMPORTANT*) To maintain the full cve-ids,
                while keeping the filename structure as is,
                I chose to store the mapping in a separate file.
AUG 5   SB KIM  Also, filter the "merge" and "revert" commits first
                in this process.
AUG 15  SB KIM  For multi-repo mode, added the path to the .git object
                at the beginning of each .diff file.
"""

import os
import subprocess
import re
import time
import argparse
import sys
import platform
import multiprocessing as mp
from functools import partial

try:
    import cPickle as pickle
except ImportError:
    import pickle

# Import from parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class InfoStruct:
    RepoName = ''  # repository name
    OriginalDir = ''  # vuddy root directory
    DiffDir = ''
    MultiModeFlag = 0
    MultiRepoList = []
    GitBinary = config.gitBinary
    GitStoragePath = config.gitStoragePath
    CveDict = {}

    def __init__(self, repoName, multiModeFlag, multiRepoList, originalDir, CveDataPath):
        self.RepoName = repoName
        self.OriginalDir = originalDir
        self.DiffDir = os.path.join(originalDir, 'diff')
        self.MultiModeFlag = multiModeFlag
        self.MultiRepoList = multiRepoList
        with open(CveDataPath, "rb") as f:
            self.CveDict = pickle.load(f)


""" GLOBALS """
originalDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # vuddy root directory
cveDataPath = os.path.join(originalDir, "cvedata.pkl")
info = InfoStruct("linux", 0, [], originalDir, cveDataPath)  # first three arg is dummy for now
printLock = mp.Lock()
#repoName = "linux"
#originalDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # vuddy root directory
#diffDir = os.path.join(originalDir, 'diff/')
#multiModeFlag = 0
#multiRepoList = []
#gitStoragePath = config.gitStoragePath
#gitBinary = config.gitBinary
#cveDict = pickle.load(open(os.path.join(originalDir, "cvedata.pkl"), "rb"))
#printLock = Lock()
# try:
#    cveDict = pickle.load(open("cvedata.pkl", "rb"))
# except IOError:  # generate
#    import NVDCVEcrawler.cveXmlDownloader as Downloader
#    import NVDCVEcrawler.cveXmlDownloader as Parser
#    import NVDCVEcrawler.cveXmlDownloader as Updater
#    print("cvedata.pkl not found, downloading automatically...")
#    Downloader.process()
#    Parser.process()
#    Updater.process()


""" FUNCTIONS """
def parse_argument():
    global info

    parser = argparse.ArgumentParser(prog='get_cvepatch_from_git.py')
    parser.add_argument('REPO',
                        help='''Repository name''')
    parser.add_argument('-m', '--multimode', action="store_true",
                        help='''Multimode''')

    args = parser.parse_args()

    info.RepoName = args.REPO
    info.MultiModeFlag = 0
    info.MultiRepoList = []
    if args.multimode:
        info.MultiModeFlag = 1
        with open(os.path.join('repolists', 'list_' + info.RepoName)) as fp:
            for repoLine in fp.readlines():
                if len(repoLine) > 2:
                    info.MultiRepoList.append(repoLine.rstrip())


def init():
    global info

    parse_argument()

    print "Retrieving CVE patch from", info.RepoName
    print "Multi-repo mode:",
    if info.MultiModeFlag:
        print "ON."
    else:
        print "OFF."

    print "Initializing...",

    try:
        os.makedirs(os.path.join(info.DiffDir + info.RepoName))
    except OSError:
        pass

    print "Done."


def callGitLog(gitDir):
    global info
    """
    Collect CVE commit log from repository
    :param gitDir: repository path
    :return:
    """
    # print "Calling git log...",
    pattern = re.compile('[\n](?=commit\s\w{40}\nAuthor:\s)|[\n](?=commit\s\w{40}\nMerge:\s)')

    commitsList = []
    if "Windows" in platform.platform():
        # --grep not works in Windows.
        # Use regex instead
        command_log = "\"{0}\" log --all --pretty=fuller".format(info.GitBinary)
        os.chdir(gitDir)
        try:
            try:
                rawLogOutput = subprocess.check_output(command_log, shell=True)
                # commitsRawList = re.split('[\n](?=commit\s\w{40}\nAuthor:\s)', rawLogOutput)
                commitsRawList = re.split(pattern, rawLogOutput)

                for commit in commitsRawList:
                    if 'CVE-20' in commit:
                        commitsList.append(commit)
            except subprocess.CalledProcessError as e:
                print "[-] Git log error:", e
        except UnicodeDecodeError as err:
            print "[-] Unicode error:", err
    else:
        grepKeyword = r"'CVE-20'"
        command_log = "\"{0}\" log --all --pretty=fuller --grep={1}".format(info.GtBinary, grepKeyword)
        os.chdir(gitDir)
        try:
            try:
                gitLogOutput = subprocess.check_output(command_log, shell=True)
                # commitsList = re.split('[\n](?=commit\s\w{40}\nAuthor:\s)|[\n](?=commit\s\w{40}\nMerge:\s)', gitLogOutput)
                commitsList = re.split(pattern, gitLogOutput)
            except subprocess.CalledProcessError as e:
                print "[-] Git log error:", e
        except UnicodeDecodeError as err:
            print "[-] Unicode error:", err

    # print "Done."
    return commitsList


def filterCommitMessage(commitMessage):
    """
    Filter false positive commits 
    Will remove 'Merge', 'Revert', 'Upgrade' commit log
    :param commitMessage: commit message
    :return: 
    """
    filterKeywordList = ["merge", "revert", "upgrade"]
    matchCnt = 0
    for kwd in filterKeywordList:
        keywordPattern = r"\W" + kwd + r"\W|\W" + kwd + r"s\W"
        compiledKeyworddPattern = re.compile(keywordPattern)
        match = compiledKeyworddPattern.search(commitMessage.lower())

        # bug fixed.. now revert and upgrade commits will be filtered out.
        if match:
            matchCnt += 1

    if matchCnt > 0:
        return 1
    else:
        return 0


def callGitShow(gitBinary, commitHashValue):
    """
    Grep data of git show
    :param commitHashValue: 
    :return: 
    """
    # print "Calling git show...",
    command_show = "\"{0}\" show --pretty=fuller {1}".format(gitBinary, commitHashValue)

    gitShowOutput = ''
    try:
        gitShowOutput = subprocess.check_output(command_show, shell=True)
    except subprocess.CalledProcessError as e:
        print "error:", e

    # print "Done."
    return gitShowOutput


def updateCveInfo(cveDict, cveId):
    """
    Get CVSS score and CWE id from CVE id
    :param cveId: 
    :return: 
    """
    # print "Updating CVE metadata...",
    try:
        cvss = cveDict[cveId][0]
    except:
        cvss = "0.0"
    if len(cvss) == 0:
        cvss = "0.0"

    try:
        cwe = cveDict[cveId][1]
    except:
        cwe = "CWE-000"
    if len(cwe) == 0:
        cwe = "CWE-000"
    else:
        cweNum = cwe.split('-')[1].zfill(3)
        cwe = "CWE-" + str(cweNum)

    # print "Done."
    return cveId + '_' + cvss + '_' + cwe + '_'


def process(commitsList, subRepoName):
    global info

    # commitsList = re.split('[\n](?=commit\s\w{40}\nAuthor:\s)|[\n](?=commit\s\w{40}\nMerge:\s)', gitLogOutput)
    print len(commitsList), "commits in", info.RepoName,
    if subRepoName is None:
        print "\n"
    else:
        print subRepoName
        os.chdir(os.path.join(info.GitStoragePath, info.RepoName, subRepoName))

    if "Windows" in platform.platform():
        # Windows - do not use multiprocessing
        # Using multiprocessing will lower performance
        for commitMessage in commitsList:
            parallel_process(subRepoName, commitMessage)
    else:  # POSIX - use multiprocessing
        pool = mp.Pool()
        parallel_partial = partial(parallel_process, subRepoName)
        pool.map(parallel_partial, commitsList)


def parallel_process(subRepoName, commitMessage):
    global info
    global printLock

    if filterCommitMessage(commitMessage):
        return
    else:
        commitHashValue = commitMessage[7:47]

        cvePattern = re.compile('CVE-20\d{2}-\d{4}')
        cveIdList = list(set(cvePattern.findall(commitMessage)))

        """    
        Note, Aug 5
        If multiple CVE ids are assigned to one commit,
        store the dependency in a file which is named after
        the repo, (e.g., ~/diff/dependency_ubuntu)    and use
        one representative CVE that has the smallest ID number
        for filename. 
        A sample:
        CVE-2014-6416_2e9466c84e5beee964e1898dd1f37c3509fa8853    CVE-2014-6418_CVE-2014-6417_CVE-2014-6416_
        """

        if len(cveIdList) > 1:  # do this only if muliple CVEs are assigned to a commit
            dependency = os.path.join(info.DiffDir, "dependency_" + info.RepoName[:-1])
            with open(dependency, "a") as fp:
                # fp = open(diffDir + "dependency_" + repoName[:-1], "a")
                cveIdFull = ""
                minCve = ""
                minimum = 9999
                for cveId in cveIdList:
                    idDigits = int(cveId.split('-')[2])
                    cveIdFull += cveId + '_'
                    if minimum > idDigits:
                        minimum = idDigits
                        minCve = cveId
                fp.write(str(minCve + '_' + commitHashValue + '\t' + cveIdFull + '\n'))
        elif len(cveIdList) == 0:
            return
        else:
            minCve = cveIdList[0]

        gitShowOutput = callGitShow(info.GitBinary, commitHashValue)

        finalFileName = updateCveInfo(info.CveDict, minCve)

        diffFileName = "{0}{1}.diff".format(finalFileName, commitHashValue)
        try:
            with open(os.path.join(info.DiffDir, info.RepoName, diffFileName), "w") as fp:
                if subRepoName is None:
                    fp.write(gitShowOutput)
                else:  # multi-repo mode
                    fp.write(subRepoName + '\n' + gitShowOutput)
            with printLock:
                print "[+] Writing {0} Done.".format(diffFileName)
        except IOError as e:
            with printLock:
                print "[+] Writing {0} Error:".format(diffFileName), e


""" main """
def main():
    global info

    t1 = time.time()
    init()
    if info.MultiModeFlag:
        for sidx, subRepoName in enumerate(info.MultiRepoList):
            gitDir = os.path.join(info.GitStoragePath, info.RepoName, subRepoName)  # where .git exists
            commitsList = callGitLog(gitDir)
            print os.path.join(str(sidx + 1), str(len(info.MultiRepoList)))
            if 0 < len(commitsList):
                process(commitsList, subRepoName)
    else:
        gitDir = os.path.join(info.GitStoragePath, info.RepoName)  # where .git exists
        commitsList = callGitLog(gitDir)
        process(commitsList, None)

    repoDiffDir = os.path.join(info.DiffDir, info.RepoName)
    print str(len(os.listdir(repoDiffDir))) + " patches saved in", repoDiffDir
    print "Done. (" + str(time.time() - t1) + " sec)"


if __name__ == '__main__':
    mp.freeze_support()
    main()
