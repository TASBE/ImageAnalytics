#!/usr/bin/env groovy

pipeline {

	options { buildDiscarder(logRotator(numToKeepStr: '5')) }

	agent { label 'linux'}

	stages {
		stage('Build') { // Setup dependencies
			steps {
				echo "NODE_NAME = ${env.NODE_NAME}"
				// Get the test repo and ensure it's setup
				dir('testRepo') {
					git url: 'git@superior.bbn.com:ELM-test'
					sh '#!/bin/sh -xe\n make'
				}
			}
		}

		stage('Test') {
			steps {
				echo "Beginning tests..."
				dir('testRepo') {
					timestamps {
						timeout(time: 2, unit: 'HOURS') {
							dir ('tests') {
								sh "#!/bin/sh -xe\n ./cellStatsTest.sh"
							}
						} // timeout
					} // timestamps
				} // dir
			} // steps
		} // stage build & test
				
	} // stages
		
	post {
		always {

			junit "**/tests/**/*.xml"

			emailext recipientProviders: [[$class: 'DevelopersRecipientProvider'], [$class: 'CulpritsRecipientProvider']], 
					to: 'elm-team-commits@rlist.app.ray.com',
					subject: '$DEFAULT_SUBJECT', 
					body: '''${PROJECT_NAME} - Build # ${BUILD_NUMBER} - ${BUILD_STATUS}

Changes:
${CHANGES}

Failed Tests:
${FAILED_TESTS, onlyRegressions=false}

Check console output at ${BUILD_URL} to view the full results.

Tail of Log:
${BUILD_LOG, maxLines=50}

'''

		} // always
	} // post

} // pipeline
