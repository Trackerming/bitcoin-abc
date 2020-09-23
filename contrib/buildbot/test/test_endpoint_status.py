#!/usr/bin/env python3
#
# Copyright (c) 2017-2019 The Bitcoin ABC developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import json
import mock
import requests
import unittest
from urllib.parse import urljoin

from build import BuildStatus
from phabricator_wrapper import BITCOIN_ABC_REPO
from server import BADGE_TC_BASE
from teamcity_wrapper import BuildInfo
from testutil import AnyWith
from test.abcbot_fixture import ABCBotFixture
import test.mocks.fixture
import test.mocks.phabricator
import test.mocks.teamcity
from test.mocks.teamcity import DEFAULT_BUILD_ID, TEAMCITY_CI_USER


class statusRequestData(test.mocks.fixture.MockData):
    def __init__(self):
        self.buildName = 'build-name'
        self.project = 'bitcoin-abc-test'
        self.buildId = DEFAULT_BUILD_ID
        self.buildTypeId = 'build-type-id'
        self.buildResult = 'success'
        self.revision = 'commitHash'
        self.branch = 'refs/heads/master'
        self.buildTargetPHID = 'buildTargetPHID'

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        if name in ['buildId', 'buildTypeId']:
            self.buildURL = urljoin(
                test.mocks.teamcity.TEAMCITY_BASE_URL,
                'viewLog.html?buildTypeId={}&buildId={}'.format(
                    getattr(self, 'buildTypeId', ''),
                    getattr(self, 'buildId', '')))


class EndpointStatusTestCase(ABCBotFixture):
    def setUp(self):
        super().setUp()
        self.phab.get_file_content_from_master = mock.Mock()
        self.phab.get_file_content_from_master.return_value = json.dumps({})

        self.phab.set_text_panel_content = mock.Mock()

        self.teamcity.getBuildInfo = mock.Mock()
        self.configure_build_info()
        self.teamcity.get_coverage_summary = mock.Mock()
        self.teamcity.get_coverage_summary.return_value = None

        self.travis.get_branch_status = mock.Mock()
        self.travis.get_branch_status.return_value = BuildStatus.Success

    def setup_master_failureAndTaskDoesNotExist(self, latestCompletedBuildId=DEFAULT_BUILD_ID,
                                                numRecentFailedBuilds=0, numCommits=1,
                                                userSearchFields=None):
        if userSearchFields is None:
            userSearchFields = {}

        self.phab.maniphest.edit.return_value = {
            'object': {
                'id': '890',
                'phid': 'PHID-TASK-890',
            },
        }

        recentBuilds = [] if numRecentFailedBuilds == 0 else [
            {'status': 'FAILURE'}, {'status': 'SUCCESS'}] * numRecentFailedBuilds
        self.teamcity.session.send.side_effect = [
            # Build failures
            test.mocks.teamcity.Response(),
            # Latest completed build
            test.mocks.teamcity.Response(json.dumps({
                'build': [{
                    'id': latestCompletedBuildId,
                }],
            })),
            test.mocks.teamcity.Response(json.dumps({
                'build': recentBuilds,
            })),
        ]

        commits = []
        for i in range(numCommits):
            commitId = 8000 + i
            commits.append({
                'phid': 'PHID-COMMIT-{}'.format(commitId),
                'fields': {
                    'identifier': 'deadbeef0000011122233344455566677788{}'.format(commitId)
                },
            })
        self.phab.diffusion.commit.search.return_value = test.mocks.phabricator.Result(
            commits)

        revisionSearchResult = test.mocks.phabricator.differential_revision_search_result(
            total=numCommits)

        revisions = []
        for i in range(numCommits):
            revisions.append({
                'sourcePHID': 'PHID-COMMIT-{}'.format(8000 + i),
                'destinationPHID': revisionSearchResult.data[i]['phid'],
            })
        self.phab.edge.search.return_value = test.mocks.phabricator.Result(
            revisions)

        self.phab.differential.revision.search.return_value = revisionSearchResult
        self.phab.user.search.return_value = test.mocks.phabricator.Result([{
            'id': '5678',
            'phid': revisionSearchResult.data[0]['fields']['authorPHID'],
            'fields': userSearchFields,
        }])

    def configure_build_info(self, **kwargs):
        self.teamcity.getBuildInfo.return_value = BuildInfo.fromSingleBuildResponse(
            json.loads(test.mocks.teamcity.buildInfo(**kwargs).content)
        )

    def test_status_invalid_json(self):
        data = "not: a valid json"
        response = self.app.post('/status', headers=self.headers, data=data)
        self.assertEqual(response.status_code, 415)

    def test_status_noData(self):
        response = self.app.post('/status', headers=self.headers)
        assert response.status_code == 415
        self.phab.harbormaster.createartifact.assert_not_called()

    def test_status_unresolved(self):
        data = statusRequestData()
        data.branch = 'UNRESOLVED'
        data.buildTargetPHID = 'UNRESOLVED'
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 400
        self.phab.harbormaster.createartifact.assert_not_called()

    def test_status_ignoredBuild(self):
        data = statusRequestData()
        data.buildTypeId = 'build-name__BOTIGNORE'
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.harbormaster.createartifact.assert_not_called()

    def test_status_master(self):
        data = statusRequestData()
        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.buildInfo_automatedBuild(),
            test.mocks.teamcity.Response(json.dumps({
                'build': [{
                    'id': DEFAULT_BUILD_ID,
                }],
            })),
        ]
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_not_called()
        self.slackbot.client.chat_postMessage.assert_not_called()

    def test_status_master_resolveBrokenBuildTask_masterGreen(self):
        def setupMockResponses():
            self.teamcity.session.send.side_effect = [
                test.mocks.teamcity.buildInfo_automatedBuild(),
                test.mocks.teamcity.Response(json.dumps({
                    'build': [{
                        'id': DEFAULT_BUILD_ID,
                    }],
                })),
                test.mocks.teamcity.Response(),
                test.mocks.teamcity.Response(),
            ]
            self.phab.maniphest.search.return_value = test.mocks.phabricator.Result([{
                'id': '123',
                'phid': 'PHID-TASK-123',
            }])
            self.phab.maniphest.edit.return_value = {
                'object': {
                    'id': '123',
                    'phid': 'PHID-TASK-123',
                },
            }

        data = statusRequestData()
        data.buildResult = 'failure'
        setupMockResponses()
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        # Master should be marked red

        data = statusRequestData()
        setupMockResponses()
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_called_with(transactions=[{
            'type': 'status',
            'value': 'resolved',
        }], objectIdentifier='PHID-TASK-123')
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='#test-dev-channel',
            text="Master is green again.")

    def test_status_master_resolveBrokenBuildTask_masterStillRed(self):
        data = statusRequestData()

        self.configure_build_info(
            triggered=test.mocks.teamcity.buildInfo_triggered(
                triggerType='user', username=TEAMCITY_CI_USER)
        )

        # Check build failure
        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.Response(json.dumps({
                'build': [{
                    'id': DEFAULT_BUILD_ID,
                }],
            })),
            test.mocks.teamcity.Response(json.dumps({
                'problemOccurrence': [{
                    'build': {
                        'buildTypeId': 'build-type',
                    },
                }],
            })),
            test.mocks.teamcity.Response(),
        ]
        self.phab.maniphest.search.return_value = test.mocks.phabricator.Result([{
            'id': '123',
            'phid': 'PHID-TASK-123',
        }])
        self.phab.maniphest.edit.return_value = {
            'object': {
                'id': '123',
                'phid': 'PHID-TASK-123',
            },
        }
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_called_with(transactions=[{
            'type': 'status',
            'value': 'resolved',
        }], objectIdentifier='PHID-TASK-123')
        self.slackbot.client.chat_postMessage.assert_not_called()

        # Check test failure
        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.Response(json.dumps({
                'build': [{
                    'id': DEFAULT_BUILD_ID,
                }],
            })),
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(json.dumps({
                'testOccurrence': [{
                    'build': {
                        'buildTypeId': 'build-type',
                    },
                }],
            })),
        ]
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_called_with(transactions=[{
            'type': 'status',
            'value': 'resolved',
        }], objectIdentifier='PHID-TASK-123')
        self.slackbot.client.chat_postMessage.assert_not_called()

    def test_status_master_resolveBrokenBuild_outOfOrderBuilds(self):
        data = statusRequestData()
        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.buildInfo_automatedBuild(),
            test.mocks.teamcity.Response(json.dumps({
                'build': [{
                    # Another build of the same type that was started after this build
                    # has already completed. Do not treat master as green/fixed based
                    # on this build, since the most recent build may have
                    # failed.
                    'id': 234567,
                }],
            })),
        ]
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_not_called()
        self.slackbot.client.chat_postMessage.assert_not_called()
        self.teamcity.session.send.assert_called_with(AnyWith(requests.PreparedRequest, {
            'url': self.teamcity.build_url(
                "app/rest/builds",
                {
                    "locator": "buildType:build-type-id",
                    "fields": "build(id)",
                    "count": 1,
                }
            )
        }))

    def test_status_infraFailure(self):
        # Test an infra failure on master
        data = statusRequestData()
        data.buildResult = 'failure'

        with open(self.data_dir / 'testlog_infrafailure.zip', 'rb') as f:
            buildLog = f.read()

        def setupTeamcity():
            self.configure_build_info(
                triggered=test.mocks.teamcity.buildInfo_triggered(
                    triggerType='user', username=TEAMCITY_CI_USER)
            )

            self.teamcity.session.send.side_effect = [
                test.mocks.teamcity.Response(json.dumps({
                    'problemOccurrence': [{
                        'id': 'id:2500,build:(id:56789)',
                    }],
                })),
                test.mocks.teamcity.Response(
                    status_code=requests.codes.not_found),
                test.mocks.teamcity.Response(buildLog),
            ]

        setupTeamcity()
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_not_called()

        def verifyInfraChannelMessage():
            self.slackbot.client.chat_postMessage.assert_called_with(
                channel='#infra-support-channel',
                text="<!subteam^S012TUC9S2Z> There was an infrastructure failure in 'build-name': {}".format(
                    self.teamcity.build_url(
                        "viewLog.html",
                        {
                            "buildTypeId": data.buildTypeId,
                            "buildId": DEFAULT_BUILD_ID,
                        }
                    )
                ))
        verifyInfraChannelMessage()

        # Test an infra failure on a revision
        data = statusRequestData()
        data.branch = 'phabricator/diff/456'
        data.buildResult = 'failure'
        setupTeamcity()
        self.phab.differential.diff.search.return_value = test.mocks.phabricator.Result([{
            'id': '456',
            'fields': {
                'revisionPHID': '789'
            },
        }])

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_called_with(transactions=[{
            "type": "comment",
            "value": "(IMPORTANT) The build failed due to an unexpected infrastructure outage. "
                     "The administrators have been notified to investigate. Sorry for the inconvenience.",
        }], objectIdentifier='789')
        self.phab.maniphest.edit.assert_not_called()
        verifyInfraChannelMessage()

    def test_status_master_failureAndTaskDoesNotExist_outOfOrderBuilds(self):
        data = statusRequestData()
        data.buildResult = 'failure'

        # Another build of the same type that was started after this build
        # has already completed. Do not treat master as red/broken based
        # on this build, since the most recent build may have succeeded.
        self.setup_master_failureAndTaskDoesNotExist(
            latestCompletedBuildId=234567)

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_not_called()
        self.slackbot.client.chat_postMessage.assert_not_called()

    def test_status_master_failureAndTaskDoesNotExist_authorDefaultName(self):
        data = statusRequestData()
        data.buildResult = 'failure'

        self.setup_master_failureAndTaskDoesNotExist(userSearchFields={
            'username': 'author-phab-username',
            'custom.abc:slack-username': '',
        })
        self.slackbot.client.users_list.return_value = test.mocks.slackbot.users_list(
            total=2)

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        maniphestEditCalls = [mock.call(transactions=[{
            "type": "title",
            "value": "Build build-name is broken.",
        }, {
            "type": "priority",
            "value": "unbreak",
        }, {
            "type": "description",
            "value": "[[ {} | build-name ]] is broken on branch 'refs/heads/master'\n\nAssociated commits:\nrABCdeadbeef00000111222333444555666777888000".format(
                self.teamcity.build_url(
                    "viewLog.html",
                    {
                        "buildTypeId": data.buildTypeId,
                        "buildId": DEFAULT_BUILD_ID,
                    }
                )
            ),
        }])]
        self.phab.maniphest.edit.assert_has_calls(
            maniphestEditCalls, any_order=False)

        self.phab.diffusion.commit.search.assert_called_with(constraints={
            "repositories": [BITCOIN_ABC_REPO],
            "identifiers": ['deadbeef00000111222333444555666777888000'],
        })
        self.phab.edge.search.assert_called_with(
            types=['commit.revision'], sourcePHIDs=['PHID-COMMIT-8000'])
        self.phab.differential.revision.search.assert_called_with(
            constraints={"phids": ['PHID-DREV-1000']})
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='#test-dev-channel',
            text="Committer: author-phab-username\n"
                 "Build 'build-name' appears to be broken: {}\n"
                 "Task: https://reviews.bitcoinabc.org/T890\n"
                 "Diff: https://reviews.bitcoinabc.org/D{}".format(
                     self.teamcity.build_url(
                         "viewLog.html",
                         {
                             "buildId": DEFAULT_BUILD_ID,
                         }
                     ),
                     test.mocks.phabricator.DEFAULT_REVISION_ID,
                 )
        )

    def test_status_master_failureAndTaskDoesNotExist_authorSlackUsername(
            self):
        data = statusRequestData()
        data.buildResult = 'failure'

        slackUserProfile = test.mocks.slackbot.userProfile(
            {'real_name': 'author-slack-username'})
        slackUser = test.mocks.slackbot.user(
            userId='U8765', profile=slackUserProfile)
        self.setup_master_failureAndTaskDoesNotExist(userSearchFields={
            'username': 'author-phab-username',
            'custom.abc:slack-username': 'author-slack-username',
        })
        self.slackbot.client.users_list.return_value = test.mocks.slackbot.users_list(
            total=2, initialUsers=[slackUser])

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        maniphestEditCalls = [mock.call(transactions=[{
            "type": "title",
            "value": "Build build-name is broken.",
        }, {
            "type": "priority",
            "value": "unbreak",
        }, {
            "type": "description",
            "value": "[[ {} | build-name ]] is broken on branch 'refs/heads/master'\n\nAssociated commits:\nrABCdeadbeef00000111222333444555666777888000".format(
                self.teamcity.build_url(
                    "viewLog.html",
                    {
                        "buildTypeId": data.buildTypeId,
                        "buildId": DEFAULT_BUILD_ID,
                    }
                )
            ),
        }])]
        self.phab.maniphest.edit.assert_has_calls(
            maniphestEditCalls, any_order=False)

        self.phab.diffusion.commit.search.assert_called_with(constraints={
            "repositories": [BITCOIN_ABC_REPO],
            "identifiers": ['deadbeef00000111222333444555666777888000'],
        })
        self.phab.edge.search.assert_called_with(
            types=['commit.revision'], sourcePHIDs=['PHID-COMMIT-8000'])
        self.phab.differential.revision.search.assert_called_with(
            constraints={"phids": ['PHID-DREV-1000']})
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='#test-dev-channel',
            text="Committer: <@U8765>\n"
                 "Build 'build-name' appears to be broken: {}\n"
                 "Task: https://reviews.bitcoinabc.org/T890\n"
                 "Diff: https://reviews.bitcoinabc.org/D{}".format(
                     self.teamcity.build_url(
                         "viewLog.html",
                         {
                             "buildId": DEFAULT_BUILD_ID,
                         }
                     ),
                     test.mocks.phabricator.DEFAULT_REVISION_ID,
                 )
        )

    def test_status_master_failureAndTaskDoesNotExist_scheduledBuild(self):
        data = statusRequestData()
        data.buildResult = 'failure'

        self.configure_build_info(
            triggered=test.mocks.teamcity.buildInfo_triggered(
                triggerType='schedule')
        )
        self.setup_master_failureAndTaskDoesNotExist()

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        maniphestEditCalls = [mock.call(transactions=[{
            "type": "title",
            "value": "Build build-name is broken.",
        }, {
            "type": "priority",
            "value": "unbreak",
        }, {
            "type": "description",
            "value": "[[ {} | build-name ]] is broken on branch 'refs/heads/master'\n\nAssociated commits:\nrABCdeadbeef00000111222333444555666777888000".format(
                self.teamcity.build_url(
                    "viewLog.html",
                    {
                        "buildTypeId": data.buildTypeId,
                        "buildId": DEFAULT_BUILD_ID,
                    }
                )
            ),
        }])]
        self.phab.maniphest.edit.assert_has_calls(
            maniphestEditCalls, any_order=False)

        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='#test-dev-channel',
            text="Scheduled build 'build-name' appears to be broken: {}\n"
                 "Task: https://reviews.bitcoinabc.org/T890".format(
                     self.teamcity.build_url(
                         "viewLog.html",
                         {
                             "buildId": DEFAULT_BUILD_ID,
                         }
                     )
                 ))

    def test_status_master_failureAndTaskDoesNotExist_multipleChanges(self):
        data = statusRequestData()
        data.buildResult = 'failure'

        self.configure_build_info(
            changes=test.mocks.teamcity.buildInfo_changes([
                'deadbeef00000111222333444555666777888000',
                'deadbeef00000111222333444555666777888001']),
            triggered=test.mocks.teamcity.buildInfo_triggered(triggerType='user',
                                                              username=test.mocks.teamcity.TEAMCITY_CI_USER),
        )

        self.setup_master_failureAndTaskDoesNotExist(
            numCommits=2, userSearchFields={
                'username': 'author-phab-username',
                'custom.abc:slack-username': '',
            })
        self.slackbot.client.users_list.return_value = test.mocks.slackbot.users_list(
            total=2)

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        maniphestEditCalls = [mock.call(transactions=[{
            "type": "title",
            "value": "Build build-name is broken.",
        }, {
            "type": "priority",
            "value": "unbreak",
        }, {
            "type": "description",
            "value": "[[ {} | build-name ]] is broken on branch 'refs/heads/master'\n\nAssociated commits:\nrABCdeadbeef00000111222333444555666777888000\nrABCdeadbeef00000111222333444555666777888001".format(
                self.teamcity.build_url(
                    "viewLog.html",
                    {
                        "buildTypeId": data.buildTypeId,
                        "buildId": DEFAULT_BUILD_ID,
                    }
                )
            ),
        }])]
        self.phab.maniphest.edit.assert_has_calls(
            maniphestEditCalls, any_order=False)

        self.phab.diffusion.commit.search.assert_called_with(constraints={
            "repositories": [BITCOIN_ABC_REPO],
            "identifiers": ['deadbeef00000111222333444555666777888000', 'deadbeef00000111222333444555666777888001'],
        })
        self.phab.edge.search.assert_called_with(
            types=['commit.revision'], sourcePHIDs=[
                'PHID-COMMIT-8000', 'PHID-COMMIT-8001'])
        self.phab.differential.revision.search.assert_called_with(
            constraints={"phids": ['PHID-DREV-1000', 'PHID-DREV-1001']})
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='#test-dev-channel',
            text="Committer: author-phab-username\n"
                 "Build 'build-name' appears to be broken: {}\n"
                 "Task: https://reviews.bitcoinabc.org/T890\n"
                 "Diff: https://reviews.bitcoinabc.org/D{}".format(
                     self.teamcity.build_url(
                         "viewLog.html",
                         {
                             "buildId": DEFAULT_BUILD_ID,
                         }
                     ),
                     test.mocks.phabricator.DEFAULT_REVISION_ID,
                 ))

    def test_status_master_failureAndTaskDoesNotExist_firstFlakyFailure(self):
        self.teamcity.setMockTime(1590000000)
        data = statusRequestData()
        data.buildResult = 'failure'

        self.setup_master_failureAndTaskDoesNotExist(numRecentFailedBuilds=2)

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()

        self.teamcity.session.send.assert_called_with(AnyWith(requests.PreparedRequest, {
            'url': self.teamcity.build_url(
                "app/rest/builds",
                {
                    "locator": "buildType:{},sinceDate:{}".format(data.buildTypeId,
                                                                  self.teamcity.formatTime(1590000000 - 60 * 60 * 24 * 5)),
                    "fields": "build",
                }
            )
        }))

        self.phab.maniphest.edit.assert_not_called()
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='#test-dev-channel',
            text="Build 'build-name' appears to be flaky: {}".format(
                self.teamcity.build_url(
                    "viewLog.html",
                    {
                        "buildId": DEFAULT_BUILD_ID,
                    }
                ))
        )

    def test_status_master_failureAndTaskDoesNotExist_successiveFlakyFailures(
            self):
        self.teamcity.setMockTime(1590000000)
        data = statusRequestData()
        data.buildResult = 'failure'

        self.setup_master_failureAndTaskDoesNotExist(numRecentFailedBuilds=3)

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()

        self.teamcity.session.send.assert_called_with(AnyWith(requests.PreparedRequest, {
            'url': self.teamcity.build_url(
                "app/rest/builds",
                {
                    "locator": "buildType:{},sinceDate:{}".format(data.buildTypeId,
                                                                  self.teamcity.formatTime(1590000000 - 60 * 60 * 24 * 5)),
                    "fields": "build",
                }
            )
        }))

        self.phab.maniphest.edit.assert_not_called()
        self.slackbot.client.chat_postMessage.assert_not_called()

    def test_status_master_failureAndTaskExists(self):
        data = statusRequestData()
        data.buildResult = 'failure'

        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.buildInfo_automatedBuild(),
            test.mocks.teamcity.Response(json.dumps({
                'build': [{
                    'id': DEFAULT_BUILD_ID,
                }],
            })),
            test.mocks.teamcity.Response(),
        ]

        self.phab.maniphest.search.return_value = test.mocks.phabricator.Result([{
            'id': '123',
        }])

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_not_called()
        self.phab.maniphest.edit.assert_not_called()

    def test_status_revision_happyPath(self):
        data = statusRequestData()
        data.branch = 'phabricator/diff/456'

        self.configure_build_info(
            properties=test.mocks.teamcity.buildInfo_properties(propsList=[{
                'name': 'env.ABC_BUILD_NAME',
                'value': 'build-diff',
            }])
        )

        self.phab.differential.revision.edit = mock.Mock()
        self.phab.differential.diff.search.return_value = test.mocks.phabricator.Result([{
            'id': '456',
            'fields': {
                'revisionPHID': '789'
            },
        }])
        self.phab.differential.revision.search.return_value = test.mocks.phabricator.differential_revision_search_result()

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200

    def test_status_revision_buildFailedWithoutDetails_OS_NAME(self):
        data = statusRequestData()
        data.buildResult = 'failure'
        data.branch = 'phabricator/diff/456'

        self.configure_build_info(
            properties=test.mocks.teamcity.buildInfo_properties(propsList=[{
                'name': 'env.OS_NAME',
                'value': 'linux',
            }]),
        )

        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(),
        ]

        self.phab.differential.revision.edit = mock.Mock()
        self.phab.differential.diff.search.return_value = test.mocks.phabricator.Result([{
            'id': '456',
            'fields': {
                'revisionPHID': '789'
            },
        }])
        self.phab.differential.revision.search.return_value = test.mocks.phabricator.differential_revision_search_result()

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.phab.differential.revision.edit.assert_called_with(transactions=[{
            "type": "comment",
            "value": "(IMPORTANT) Build [[{} | build-name (linux)]] failed.".format(
                self.teamcity.build_url(
                    "viewLog.html",
                    {
                        "buildTypeId": data.buildTypeId,
                        "buildId": DEFAULT_BUILD_ID,
                    }
                )
            ),
        }], objectIdentifier='789')

    def test_status_revision_buildFailedWithoutDetails(self):
        data = statusRequestData()
        data.buildResult = 'failure'
        data.branch = 'phabricator/diff/789'

        self.phab.differential.revision.edit = mock.Mock()
        self.phab.differential.diff.search.return_value = test.mocks.phabricator.Result([{
            'id': '789',
            'fields': {
                'revisionPHID': '123'
            },
        }])
        self.phab.differential.revision.search.return_value = test.mocks.phabricator.differential_revision_search_result()

        self.configure_build_info(
            properties=test.mocks.teamcity.buildInfo_properties(propsList=[{
                'name': 'env.ABC_BUILD_NAME',
                'value': 'build-diff',
            }])
        )

        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(),
        ]

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.teamcity.session.send.assert_called_with(AnyWith(requests.PreparedRequest, {
            'url': self.teamcity.build_url(
                "app/rest/testOccurrences",
                {
                    "locator": "build:(id:{}),status:FAILURE".format(DEFAULT_BUILD_ID),
                    "fields": "testOccurrence(id,details,name)",
                }
            )
        }))
        self.phab.differential.revision.edit.assert_called_with(transactions=[{
            "type": "comment",
            "value": "(IMPORTANT) Build [[{} | build-name (build-diff)]] failed.".format(
                self.teamcity.build_url(
                    "viewLog.html",
                    {
                        "buildTypeId": data.buildTypeId,
                        "buildId": DEFAULT_BUILD_ID,
                    }
                )
            ),
        }], objectIdentifier='123')

    def test_status_revision_buildFailedWithDetails(self):
        data = statusRequestData()
        data.buildResult = 'failure'
        data.branch = 'phabricator/diff/789'

        self.phab.differential.revision.edit = mock.Mock()
        self.phab.differential.diff.search.return_value = test.mocks.phabricator.Result([{
            'id': '789',
            'fields': {
                'revisionPHID': '123'
            },
        }])
        self.phab.differential.revision.search.return_value = test.mocks.phabricator.differential_revision_search_result()

        with open(self.data_dir / 'testlog.zip', 'rb') as f:
            buildLog = f.read()
        with open(self.data_dir / 'testlog.output.txt', 'r', encoding='utf-8') as f:
            expectedLogOutput = f.read()

        self.configure_build_info(
            properties=test.mocks.teamcity.buildInfo_properties(propsList=[{
                'name': 'env.ABC_BUILD_NAME',
                'value': 'build-diff',
            }])
        )

        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(json.dumps({
                'problemOccurrence': [{
                    'id': 'id:2500,build:(id:56789)',
                    # The first build failure:
                    'details': 'Process exited with code 2 (Step: Command Line)',
                }, {
                    'id': 'id:2620,build:(id:56789)',
                    # A line from the log that appears after the first failure:
                    'details': 'No reports found for paths:',
                }],
            })),
            test.mocks.teamcity.Response(status_code=requests.codes.not_found),
            test.mocks.teamcity.Response(buildLog),
            test.mocks.teamcity.Response(),
        ]

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.teamcity.session.send.assert_called_with(AnyWith(requests.PreparedRequest, {
            'url': self.teamcity.build_url(
                "app/rest/testOccurrences",
                {
                    "locator": "build:(id:{}),status:FAILURE".format(DEFAULT_BUILD_ID),
                    "fields": "testOccurrence(id,details,name)",
                }
            )
        }))
        self.phab.differential.revision.edit.assert_called_with(transactions=[{
            "type": "comment",
            "value": "(IMPORTANT) Build [[{} | build-name (build-diff)]] failed.\n\n"
                     "Snippet of first build failure:\n```lines=16,COUNTEREXAMPLE\n{}```".format(
                         self.teamcity.build_url(
                             "viewLog.html",
                             {
                                 "tab": "buildLog",
                                 "logTab": "tree",
                                 "filter": "debug",
                                 "expand": "all",
                                 "buildId": DEFAULT_BUILD_ID,
                             },
                             "footer"
                         ),
                         expectedLogOutput
                     ),
        }], objectIdentifier='123')

        # Build log taken from the artifacts
        expected_log = b'What a wonderful log !\nBut not very helpful.\nSome failure message\n'

        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(json.dumps({
                'problemOccurrence': [{
                    'id': 'id:2500,build:(id:56789)',
                    # The first build failure:
                    'details': 'Some failure message',
                }],
            })),
            test.mocks.teamcity.Response(expected_log),
            test.mocks.teamcity.Response(),
        ]

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.teamcity.session.send.assert_called_with(AnyWith(requests.PreparedRequest, {
            'url': self.teamcity.build_url(
                "app/rest/testOccurrences",
                {
                    "locator": "build:(id:{}),status:FAILURE".format(DEFAULT_BUILD_ID),
                    "fields": "testOccurrence(id,details,name)",
                }
            )
        }))
        self.phab.differential.revision.edit.assert_called_with(transactions=[{
            "type": "comment",
            "value": "(IMPORTANT) Build [[{} | build-name (build-diff)]] failed.\n\n"
                     "Snippet of first build failure:\n```lines=16,COUNTEREXAMPLE\n{}```".format(
                         self.teamcity.build_url(
                             "viewLog.html",
                             {
                                 "tab": "buildLog",
                                 "logTab": "tree",
                                 "filter": "debug",
                                 "expand": "all",
                                 "buildId": DEFAULT_BUILD_ID,
                             },
                             "footer"
                         ),
                         expected_log.decode('utf-8')
                     ),
        }], objectIdentifier='123')

    def test_status_revision_testsFailedWithDetails(self):
        data = statusRequestData()
        data.branch = 'phabricator/diff/456'
        data.buildResult = 'failure'

        self.phab.differential.revision.edit = mock.Mock()
        self.phab.differential.diff.search.return_value = test.mocks.phabricator.Result([{
            'id': '456',
            'fields': {
                'revisionPHID': '789'
            },
        }])
        self.phab.differential.revision.search.return_value = test.mocks.phabricator.differential_revision_search_result()

        failures = [{
            'id': 'id:2500,build:(id:{})'.format(DEFAULT_BUILD_ID),
            'details': 'stacktrace',
            'name': 'test name',
        }, {
            'id': 'id:2620,build:(id:{})'.format(DEFAULT_BUILD_ID),
            'details': 'stacktrace2',
            'name': 'other test name',
        }]

        self.configure_build_info(
            properties=test.mocks.teamcity.buildInfo_properties(propsList=[{
                'name': 'env.ABC_BUILD_NAME',
                'value': 'build-diff',
            }])
        )

        self.teamcity.session.send.side_effect = [
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(),
            test.mocks.teamcity.Response(json.dumps({
                'testOccurrence': failures,
            }))
        ]

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200
        self.teamcity.session.send.assert_called_with(AnyWith(requests.PreparedRequest, {
            'url': self.teamcity.build_url(
                "app/rest/testOccurrences",
                {
                    "locator": "build:(id:{}),status:FAILURE".format(DEFAULT_BUILD_ID),
                    "fields": "testOccurrence(id,details,name)",
                }
            )
        }))
        self.phab.differential.revision.edit.assert_called_with(transactions=[{
            "type": "comment",
            "value": "(IMPORTANT) Build [[{} | build-name (build-diff)]] failed.\n\n"
                     "Each failure log is accessible here:\n"
                     "[[{} | test name]]\n"
                     "[[{} | other test name]]".format(
                         self.teamcity.build_url(
                             "viewLog.html",
                             {
                                 "buildTypeId": data.buildTypeId,
                                 "buildId": DEFAULT_BUILD_ID,
                             }
                         ),
                         self.teamcity.build_url(
                             "viewLog.html",
                             {
                                 "tab": "buildLog",
                                 "logTab": "tree",
                                 "filter": "debug",
                                 "expand": "all",
                                 "buildId": DEFAULT_BUILD_ID,
                                 "_focus": 2500,
                             }
                         ),
                         self.teamcity.build_url(
                             "viewLog.html",
                             {
                                 "tab": "buildLog",
                                 "logTab": "tree",
                                 "filter": "debug",
                                 "expand": "all",
                                 "buildId": DEFAULT_BUILD_ID,
                                 "_focus": 2620,
                             }
                         )
                     ),
        }], objectIdentifier='789')

    def test_status_build_link_to_harbormaster(self):
        data = statusRequestData()
        data.buildTargetPHID = "PHID-HMBT-01234567890123456789"

        def call_build(build_id=DEFAULT_BUILD_ID, build_name=data.buildName):
            self.teamcity.session.send.side_effect = [
                test.mocks.teamcity.buildInfo(
                    build_id=build_id, buildqueue=True),
            ]
            url = 'build?buildTypeId=staging&ref=refs/tags/phabricator/diffs/{}&PHID={}&abcBuildName={}'.format(
                build_id,
                data.buildTargetPHID,
                build_name
            )
            response = self.app.post(url, headers=self.headers)
            assert response.status_code == 200

        # Set the status to 'running' to prevent target removal on completion.
        data.buildResult = "running"
        # Add some build target or there is no harbormaster build to link.
        call_build()

        def call_status_check_artifact_search(build_id=DEFAULT_BUILD_ID):
            self.teamcity.session.send.side_effect = [
                test.mocks.teamcity.buildInfo_automatedBuild(),
                test.mocks.teamcity.buildInfo(build_id=build_id),
            ]
            response = self.app.post(
                '/status', headers=self.headers, json=data)
            assert response.status_code == 200

            self.phab.harbormaster.artifact.search.assert_called_with(
                constraints={
                    "buildTargetPHIDs": ["PHID-HMBT-01234567890123456789"],
                }
            )

        def check_createartifact(build_id=DEFAULT_BUILD_ID,
                                 build_name=data.buildName):
            self.phab.harbormaster.createartifact.assert_called_with(
                buildTargetPHID="PHID-HMBT-01234567890123456789",
                artifactKey=build_name + "-PHID-HMBT-01234567890123456789",
                artifactType="uri",
                artifactData={
                    "uri": self.teamcity.build_url(
                        "viewLog.html",
                        {
                            "buildTypeId": data.buildTypeId,
                            "buildId": build_id,
                        }
                    ),
                    "name": build_name,
                    "ui.external": True,
                }
            )

        # On first call the missing URL artifact should be added
        call_status_check_artifact_search()
        check_createartifact()

        # Furher calls to artifact.search will return our added URL artifact
        artifact_search_return_value = {
            "id": 123,
            "phid": "PHID-HMBA-abcdefghijklmnopqrst",
            "fields": {
                "buildTargetPHID": "PHID-HMBT-01234567890123456789",
                "artifactType": "uri",
                "artifactKey": data.buildName + "-PHID-HMBT-01234567890123456789",
                "isReleased": True,
                "dateCreated": 0,
                "dateModified": 0,
                "policy": {},
            }
        }
        self.phab.harbormaster.artifact.search.return_value = test.mocks.phabricator.Result(
            [artifact_search_return_value])

        # Reset the call counter
        self.phab.harbormaster.createartifact.reset_mock()

        # Call /status again a few time
        for i in range(10):
            call_status_check_artifact_search()

            # But since the artifact already exists it is not added again
            self.phab.harbormaster.createartifact.assert_not_called()

        # If the artifact key is not the expected one, the link is added
        artifact_search_return_value["fields"]["artifactKey"] = "unexpectedArtifactKey"
        self.phab.harbormaster.artifact.search.return_value = test.mocks.phabricator.Result(
            [artifact_search_return_value])

        call_status_check_artifact_search()
        check_createartifact()

        # Add a few more builds to the build target
        for i in range(1, 1 + 5):
            build_id = DEFAULT_BUILD_ID + i
            build_name = 'build-{}'.format(i)

            data.buildName = build_name
            data.buildId = build_id
            data.buildTypeId = data.buildTypeId

            call_build(build_id, build_name)

            # Check the artifact is searched and add for each build
            call_status_check_artifact_search(build_id)
            check_createartifact(build_id, build_name)

    def test_status_landbot(self):
        data = statusRequestData()
        data.buildTypeId = 'BitcoinAbcLandBot'

        # Side effects are only valid once per call, so we need to set side_effect
        # for every call to the endpoint.
        def setupTeamcity():
            self.configure_build_info(
                properties=test.mocks.teamcity.buildInfo_properties(
                    propsList=[{
                        'name': 'env.ABC_REVISION',
                        'value': 'D1234',
                    }]
                )
            )

            self.teamcity.session.send.side_effect = [
                test.mocks.teamcity.Response(),
            ]

        def setupUserSearch(slackUsername):
            self.phab.user.search.return_value = test.mocks.phabricator.Result([{
                'id': '5678',
                'phid': revisionSearchResult.data[0]['fields']['authorPHID'],
                'fields': {
                    'username': 'author-phab-username',
                    'custom.abc:slack-username': slackUsername,
                },
            }])

            slackUserProfile = test.mocks.slackbot.userProfile(
                {'real_name': 'author-slack-username'})
            slackUser = test.mocks.slackbot.user(
                userId='U8765', profile=slackUserProfile)
            self.slackbot.client.users_list.return_value = test.mocks.slackbot.users_list(
                total=2, initialUsers=[slackUser])

        revisionSearchResult = test.mocks.phabricator.differential_revision_search_result()
        self.phab.differential.revision.search.return_value = revisionSearchResult

        expectedBuildUrl = self.teamcity.build_url(
            "viewLog.html",
            {
                "buildTypeId": data.buildTypeId,
                "buildId": DEFAULT_BUILD_ID,
            }
        )

        # Test happy path
        setupTeamcity()
        setupUserSearch(slackUsername='author-slack-username')
        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200

        self.phab.differential.revision.search.assert_called_with(constraints={
                                                                  'ids': [1234]})
        self.phab.user.search.assert_called_with(
            constraints={'phids': [revisionSearchResult.data[0]['fields']['authorPHID']]})
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='U8765',
            text="Successfully landed your change:\n"
                 "Revision: https://reviews.bitcoinabc.org/D1234\n"
                 "Build: {}".format(expectedBuildUrl),
        )

        # Test direct message on a landbot build failure
        data.buildResult = 'failure'
        setupTeamcity()
        setupUserSearch(slackUsername='author-slack-username')

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200

        self.phab.differential.revision.search.assert_called_with(constraints={
                                                                  'ids': [1234]})
        self.phab.user.search.assert_called_with(
            constraints={'phids': [revisionSearchResult.data[0]['fields']['authorPHID']]})
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='U8765',
            text="Failed to land your change:\n"
                 "Revision: https://reviews.bitcoinabc.org/D1234\n"
                 "Build: {}".format(expectedBuildUrl),
        )

        # Test message on build failure when the author's slack username is
        # unknown
        setupUserSearch(slackUsername='')
        setupTeamcity()

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200

        self.phab.differential.revision.search.assert_called_with(constraints={
                                                                  'ids': [1234]})
        self.phab.user.search.assert_called_with(
            constraints={'phids': [revisionSearchResult.data[0]['fields']['authorPHID']]})
        self.slackbot.client.chat_postMessage.assert_called_with(
            channel='#test-dev-channel',
            text="author-phab-username: Please set your slack username in your Phabricator profile so the "
                 "landbot can send you direct messages: https://reviews.bitcoinabc.org/people/editprofile/5678\n"
                 "Failed to land your change:\n"
                 "Revision: https://reviews.bitcoinabc.org/D1234\n"
                 "Build: {}".format(expectedBuildUrl),
        )

        # Make sure no messages are sent on running status
        data.buildResult = 'running'
        setupTeamcity()
        self.phab.differential.revision.search = mock.Mock()
        self.phab.user.search = mock.Mock()
        self.slackbot.client.chat_postMessage = mock.Mock()

        response = self.app.post('/status', headers=self.headers, json=data)
        assert response.status_code == 200

        self.phab.differential.revision.search.assert_not_called()
        self.phab.user.search.assert_not_called()
        self.slackbot.client.chat_postMessage.assert_not_called()

    def test_update_build_status_panel(self):
        panel_id = 17

        self.phab.get_file_content_from_master = mock.Mock()
        self.phab.set_text_panel_content = mock.Mock()

        associated_builds = {}
        self.teamcity.associate_configuration_names = mock.Mock()
        self.teamcity.associate_configuration_names.return_value = associated_builds

        # List of failing build types
        failing_build_type_ids = []
        # List of builds that did not complete yet
        no_complete_build_type_ids = []

        # Builds with ID 42 are failures
        self.teamcity.getLatestCompletedBuild = mock.Mock()
        self.teamcity.getLatestCompletedBuild.side_effect = lambda build_type_id: (
            {'id': 42} if build_type_id in failing_build_type_ids
            else None if build_type_id in no_complete_build_type_ids
            else {'id': DEFAULT_BUILD_ID}
        )

        build_info = BuildInfo.fromSingleBuildResponse(
            json.loads(test.mocks.teamcity.buildInfo().content)
        )

        def _get_build_info(build_id):
            status = BuildStatus.Failure if build_id == 42 else BuildStatus.Success
            build_info['id'] = build_id
            build_info['status'] = status.value.upper()
            build_info['statusText'] = "Build success" if status == BuildStatus.Success else "Build failure"
            return build_info

        self.teamcity.getBuildInfo.side_effect = _get_build_info

        def get_travis_panel_content(status=None):
            if not status:
                status = BuildStatus.Success

            return (
                '| secp256k1 ([[https://github.com/Bitcoin-ABC/secp256k1 | Github]]) | Status |\n'
                '|---|---|\n'
                '| [[https://travis-ci.org/github/bitcoin-abc/secp256k1 | master]] | {{image uri="https://raster.shields.io/static/v1?label=Travis build&message={}&color={}&logo=travis", alt="{}"}} |\n\n'
            ).format(
                status.value,
                'brightgreen' if status == BuildStatus.Success else 'red',
                status.value,
            )

        def set_config_file(names_to_display, names_to_hide):
            config = {"builds": {}}
            builds = config["builds"]
            for build_name in names_to_display:
                builds[build_name] = {"hideOnStatusPanel": False}
            for build_name in names_to_hide:
                builds[build_name] = {"hideOnStatusPanel": True}

            self.phab.get_file_content_from_master.return_value = json.dumps(
                config)

        def associate_build(name, teamcity_build_type_id=None, teamcity_build_name=None,
                            teamcity_project_id=None, teamcity_project_name=None):
            if not teamcity_build_type_id:
                teamcity_build_type_id = "{}_Type".format(name)
            if not teamcity_build_name:
                teamcity_build_name = "My Build {}".format(name)
            if not teamcity_project_id:
                teamcity_project_id = "ProjectId"
            if not teamcity_project_name:
                teamcity_project_name = "Project Name"

            associated_builds[name] = {
                "teamcity_build_type_id": teamcity_build_type_id,
                "teamcity_build_name": teamcity_build_name,
                "teamcity_project_id": teamcity_project_id,
                "teamcity_project_name": teamcity_project_name,
            }
            self.teamcity.associate_configuration_names.return_value = associated_builds

        def call_status(build_type_id, status, branch=None,
                        expected_status_code=None):
            data = statusRequestData()
            data.buildResult = status.value
            data.buildTypeId = build_type_id
            if branch:
                data.branch = branch

            response = self.app.post(
                '/status', headers=self.headers, json=data)
            assert response.status_code == (
                200 if not expected_status_code else expected_status_code)

        def assert_panel_content(content):
            self.phab.set_text_panel_content.assert_called_with(
                panel_id,
                content
            )

        def header(project_name):
            header = '| {} | Status |\n'.format(project_name)
            header += '|---|---|\n'
            return header

        def build_line(build_name, status=None, build_type_id=None,
                       teamcity_build_name=None):
            if not status:
                status = BuildStatus.Success
            if not build_type_id:
                build_type_id = "{}_Type".format(build_name)
            if not teamcity_build_name:
                teamcity_build_name = "My Build {}".format(build_name)

            url = self.teamcity.build_url(
                "viewLog.html",
                {
                    "buildTypeId": build_type_id,
                    "buildId": "lastFinished"
                }
            )
            status_message = "Build failure" if status == BuildStatus.Failure else status.value
            badge_url = BADGE_TC_BASE.get_badge_url(
                message=status_message,
                color=(
                    'lightgrey' if status == BuildStatus.Unknown
                    else 'brightgreen' if status == BuildStatus.Success
                    else 'red'
                ),
            )
            return '| [[{} | {}]] | {{image uri="{}", alt="{}"}} |\n'.format(
                url,
                teamcity_build_name,
                badge_url,
                status_message,
            )

        # No build in config file, should bail out and not edit the panel with
        # teamcity content
        set_config_file([], [])
        call_status('dont_care', BuildStatus.Success)
        assert_panel_content(get_travis_panel_content())

        # If branch is not master the panel is not updated
        self.phab.set_text_panel_content.reset_mock()
        call_status(
            'dont_care',
            BuildStatus.Success,
            branch='refs/tags/phabricator/diff/42',
            expected_status_code=500
        )
        self.phab.set_text_panel_content.assert_not_called()

        # Turn travis build into failure
        self.travis.get_branch_status.return_value = BuildStatus.Failure
        call_status('dont_care', BuildStatus.Success)
        assert_panel_content(get_travis_panel_content(BuildStatus.Failure))
        self.travis.get_branch_status.return_value = BuildStatus.Success

        # Some builds in config file but no associated teamcity build
        set_config_file(["show_me11"], [])
        call_status('dont_care', BuildStatus.Success)
        assert_panel_content(get_travis_panel_content())

        # Set one build to be shown and associate it. This is not the build that
        # just finished.
        associate_build("show_me11")
        call_status('hide_me_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name') +
            build_line('show_me11') +
            '\n'
        )

        # Now with 3 builds from the same project + 1 not shown
        set_config_file(["show_me11", "show_me12", "show_me13"], ["hidden"])
        associate_build("show_me12")
        associate_build("show_me13")
        call_status('hide_me_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name') +
            build_line('show_me11') +
            build_line('show_me12') +
            build_line('show_me13') +
            '\n'
        )

        # Add 2 more builds from another project.
        # Check the result is always the same after a few calls
        set_config_file(["show_me11", "show_me12", "show_me13",
                         "show_me21", "show_me22"], [])
        associate_build(
            "show_me21",
            teamcity_project_id="ProjectId2",
            teamcity_project_name="Project Name 2")
        associate_build(
            "show_me22",
            teamcity_project_id="ProjectId2",
            teamcity_project_name="Project Name 2")
        for i in range(10):
            call_status('hide_me_Type', BuildStatus.Success)
            assert_panel_content(
                get_travis_panel_content() +

                header('Project Name') +
                build_line('show_me11') +
                build_line('show_me12') +
                build_line('show_me13') +
                '\n' +

                header('Project Name 2') +
                build_line('show_me21') +
                build_line('show_me22') +
                '\n'
            )

        # Remove a build from teamcity, but not from the config file
        del associated_builds["show_me12"]
        call_status('hide_me_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name') +
            build_line('show_me11') +
            build_line('show_me13') +
            '\n' +

            header('Project Name 2') +
            build_line('show_me21') +
            build_line('show_me22') +
            '\n'
        )

        # Hide a build from the config file (cannot be associated anymore)
        set_config_file(["show_me11", "show_me12",
                         "show_me21", "show_me22"], ["show_me13"])
        del associated_builds["show_me13"]
        call_status('hide_me_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name') +
            build_line('show_me11') +
            '\n' +

            header('Project Name 2') +
            build_line('show_me21') +
            build_line('show_me22') +
            '\n'
        )

        # Remove the last build from a project and check the project is no
        # longer shown
        del associated_builds["show_me11"]
        call_status('hide_me_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name 2') +
            build_line('show_me21') +
            build_line('show_me22') +
            '\n'
        )

        # Check the status of the build is not checked if it didn't finish
        # through the endpoint
        failing_build_type_ids = ['show_me21_Type']
        call_status('hide_me_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name 2') +
            build_line('show_me21') +
            build_line('show_me22') +
            '\n'
        )

        # But having the build to be updated through the endpoint causes the
        # status to be fetched again. Note that the result is meaningless here,
        # and will be fetched from Teamcity anyway.
        call_status('show_me21_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name 2') +
            build_line('show_me21', status=BuildStatus.Failure) +
            build_line('show_me22') +
            '\n'
        )

        # Check the unknown status of a build if it never completed
        associate_build(
            "show_me23",
            teamcity_project_id="ProjectId2",
            teamcity_project_name="Project Name 2")
        no_complete_build_type_ids = ['show_me23_Type']
        call_status('show_me21_Type', BuildStatus.Success)
        assert_panel_content(
            get_travis_panel_content() +

            header('Project Name 2') +
            build_line('show_me21', status=BuildStatus.Failure) +
            build_line('show_me22') +
            build_line('show_me23', status=BuildStatus.Unknown) +
            '\n'
        )

    def test_update_coverage_panel(self):
        panel_id = 21

        self.phab.set_text_panel_content = mock.Mock()

        self.teamcity.get_coverage_summary.return_value = "Dummy"

        def call_status(status, expected_status_code=None):
            data = statusRequestData()
            data.buildResult = status.value

            response = self.app.post(
                '/status', headers=self.headers, json=data)
            assert response.status_code == (
                200 if not expected_status_code else expected_status_code)

        def assert_panel_content(content):
            self.phab.set_text_panel_content.assert_called_with(
                panel_id,
                content
            )

        def _assert_not_called_with(self, *args, **kwargs):
            try:
                self.assert_called_with(*args, **kwargs)
            except AssertionError:
                return
            raise AssertionError(
                'Expected {} to not have been called.'.format(
                    self._format_mock_call_signature(
                        args, kwargs)))
        mock.Mock.assert_not_called_with = _assert_not_called_with

        # Build failed: ignore
        call_status(BuildStatus.Failure, expected_status_code=500)
        self.phab.set_text_panel_content.assert_not_called_with(
            panel_id=panel_id)

        # No coverage report artifact: ignore
        self.teamcity.get_coverage_summary.return_value = None
        call_status(BuildStatus.Success, expected_status_code=500)
        self.phab.set_text_panel_content.assert_not_called_with(
            panel_id=panel_id)

        self.teamcity.get_coverage_summary.return_value = \
            """
Reading tracefile check-extended_combined.info
Summary coverage rate:
  lines......: 82.3% (91410 of 111040 lines)
  functions..: 74.1% (6686 of 9020 functions)
  branches...: 45.0% (188886 of 420030 branches)
"""

        call_status(BuildStatus.Success, expected_status_code=500)
        assert_panel_content(
            """**[[ https://build.bitcoinabc.org/viewLog.html?buildId=lastSuccessful&buildTypeId=BitcoinABC_Master_BitcoinAbcMasterCoverage&tab=report__Root_Code_Coverage&guest=1 | HTML coverage report ]]**

| Granularity | % hit | # hit | # total |
| ----------- | ----- | ----- | ------- |
| Lines | 82.3% | 91410 | 111040 |
| Functions | 74.1% | 6686 | 9020 |
| Branches | 45.0% | 188886 | 420030 |
"""
        )


if __name__ == '__main__':
    unittest.main()
