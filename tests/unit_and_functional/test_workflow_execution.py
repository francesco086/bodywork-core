# bodywork - MLOps on Kubernetes.
# Copyright (C) 2020-2021  Bodywork Machine Learning Ltd.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Test Bodywork workflow execution.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY
from typing import Iterable

import requests
from pytest import raises
from _pytest.capture import CaptureFixture
from kubernetes import client as k8sclient

from bodywork.constants import PROJECT_CONFIG_FILENAME, GIT_COMMIT_HASH_K8S_ENV_VAR
from bodywork.exceptions import BodyworkWorkflowExecutionError
from bodywork.workflow_execution import (
    image_exists_on_dockerhub,
    parse_dockerhub_image_string,
    run_workflow,
    _print_logs_to_stdout,
)


@patch("requests.Session")
def test_image_exists_on_dockerhub_handles_connection_error(
    mock_requests_session: MagicMock,
):
    mock_requests_session().get.side_effect = requests.exceptions.ConnectionError
    with raises(RuntimeError, match="cannot connect to"):
        image_exists_on_dockerhub("bodywork-ml/bodywork-core", "latest")


@patch("requests.Session")
def test_image_exists_on_dockerhub_handles_correctly_identifies_image_repos(
    mock_requests_session: MagicMock,
):
    mock_requests_session().get.return_value = requests.Response()

    mock_requests_session().get.return_value.status_code = 200
    assert image_exists_on_dockerhub("bodywork-ml/bodywork-core", "v1") is True

    mock_requests_session().get.return_value.status_code = 404
    assert image_exists_on_dockerhub("bodywork-ml/bodywork-core", "x") is False


def test_parse_dockerhub_image_string_raises_exception_for_invalid_strings():
    with raises(
        ValueError, match=f"invalid DOCKER_IMAGE specified in {PROJECT_CONFIG_FILENAME}"
    ):
        parse_dockerhub_image_string("bodyworkml-bodywork-stage-runner:latest")
        parse_dockerhub_image_string("bodyworkml/bodywork-core:lat:st")


def test_parse_dockerhub_image_string_parses_valid_strings():
    assert parse_dockerhub_image_string("bodyworkml/bodywork-core:0.0.1") == (
        "bodyworkml/bodywork-core",
        "0.0.1",
    )
    assert parse_dockerhub_image_string("bodyworkml/bodywork-core") == (
        "bodyworkml/bodywork-core",
        "latest",
    )


@patch("bodywork.workflow_execution.k8s")
def test_run_workflow_raises_exception_if_namespace_does_not_exist(
    mock_k8s: MagicMock,
    setup_bodywork_test_project: Iterable[bool],
    project_repo_location: Path,
):
    mock_k8s.namespace_exists.return_value = False
    with raises(BodyworkWorkflowExecutionError, match="not a valid namespace"):
        run_workflow("foo_bar_foo_993", project_repo_location)


@patch("bodywork.workflow_execution.k8s")
def test_print_logs_to_stdout(mock_k8s: MagicMock, capsys: CaptureFixture):
    mock_k8s.get_latest_pod_name.return_value = "bodywork-test-project--stage-1"
    mock_k8s.get_pod_logs.return_value = "foo-bar"
    _print_logs_to_stdout("the-namespace", "bodywork-test-project--stage-1")
    captured_stdout = capsys.readouterr().out
    assert "foo-bar" in captured_stdout

    mock_k8s.get_latest_pod_name.return_value = None
    _print_logs_to_stdout("the-namespace", "bodywork-test-project--stage-1")
    captured_stdout = capsys.readouterr().out
    assert "cannot get logs for bodywork-test-project--stage-1" in captured_stdout

    mock_k8s.get_latest_pod_name.side_effect = Exception
    _print_logs_to_stdout("the-namespace", "bodywork-test-project--stage-1")
    captured_stdout = capsys.readouterr().out
    assert "cannot get logs for bodywork-test-project--stage-1" in captured_stdout


@patch("bodywork.workflow_execution.rmtree")
@patch("bodywork.workflow_execution.requests")
@patch("bodywork.workflow_execution.download_project_code_from_repo")
@patch("bodywork.workflow_execution.get_git_commit_hash")
@patch("bodywork.workflow_execution.k8s")
def test_run_workflow_adds_git_commit_to_batch_and_service_env_vars(
    mock_k8s: MagicMock,
    mock_git_hash: MagicMock,
    mock_git_download: MagicMock,
    mock_requests: MagicMock,
    mock_rmtree: MagicMock,
    project_repo_location: Path,
):
    commit_hash = "MY GIT COMMIT HASH"
    mock_git_hash.return_value = commit_hash
    expected_result = [
        k8sclient.V1EnvVar(name=GIT_COMMIT_HASH_K8S_ENV_VAR, value=commit_hash)
    ]
    mock_k8s.create_k8s_environment_variables.return_value = expected_result
    mock_k8s.configure_env_vars_from_secrets.return_value = []

    run_workflow(
        "foo_bar_foo_993", project_repo_location, cloned_repo_dir=project_repo_location
    )

    mock_k8s.configure_service_stage_deployment.assert_called_once_with(
        ANY,
        ANY,
        ANY,
        ANY,
        ANY,
        replicas=ANY,
        port=ANY,
        container_env_vars=expected_result,
        image=ANY,
        cpu_request=ANY,
        memory_request=ANY,
        seconds_to_be_ready_before_completing=ANY,
    )
    mock_k8s.configure_batch_stage_job.assert_called_with(
        ANY,
        ANY,
        ANY,
        ANY,
        ANY,
        retries=ANY,
        container_env_vars=expected_result,
        image=ANY,
        cpu_request=ANY,
        memory_request=ANY,
    )
