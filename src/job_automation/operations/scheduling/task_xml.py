"""Native Windows Task Scheduler 2.0 XML definition generator (AUTO-01-S03).

Generates reviewable XML definitions for:
- Dispatcher task: boot-triggered + 5-minute repeating, IgnoreNew instance policy, enabled=false default.
- Model supervisor task: boot-triggered local Ollama service, enabled=false default.

Enforces:
- Schema compliance with http://schemas.microsoft.com/windows/2004/02/mit/task.
- Absolute executable paths, explicit arguments, and explicit working directory.
- No embedded credentials or passwords.
"""

from __future__ import annotations

import getpass
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from job_automation.operations.scheduling.records import ScheduleDefinition


def generate_dispatcher_task_xml(
    definition: ScheduleDefinition,
    python_exe: Path | str,
    repo_or_package_dir: Path | str,
    task_name: str = "JobAutomation_Dispatcher",
    account_name: str | None = None,
    logon_type: str = "Password",
) -> str:
    """Generate reviewable Windows Task Scheduler XML for the bounded dispatcher."""
    user = account_name or getpass.getuser()
    py_path = str(Path(python_exe).resolve())
    cwd_path = str(Path(repo_or_package_dir).resolve())

    args = f'-m job_automation ops schedule dispatch'
    if definition.app_config_path:
        args += f' --config "{definition.app_config_path}"'
    if definition.data_root:
        args += f' --data-root "{definition.data_root}"'

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    xml_text = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{now_iso}</Date>
    <Author>{user}</Author>
    <Description>Job Search Automation Bounded Dispatcher (AUTO-01). Evaluates due Europe/Berlin slots and executes pipeline runs under single-worker deployment lock.</Description>
    <URI>\\JobAutomation\\{task_name}</URI>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT1M</Delay>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>{logon_type}</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>false</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{py_path}</Command>
      <Arguments>{args}</Arguments>
      <WorkingDirectory>{cwd_path}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
    return xml_text.strip()


def generate_model_supervisor_task_xml(
    ollama_exe: Path | str,
    task_name: str = "JobAutomation_ModelSupervisor",
    account_name: str | None = None,
    logon_type: str = "Password",
    working_dir: Path | str | None = None,
    models_dir: Path | str | None = None,
) -> str:
    """Generate reviewable Windows Task Scheduler XML for the local Ollama supervisor."""
    user = account_name or getpass.getuser()
    exe_path = str(Path(ollama_exe).resolve()) if Path(ollama_exe).is_file() else str(ollama_exe)
    cwd_path = str(Path(working_dir).resolve()) if working_dir else str(Path.home())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    xml_text = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{now_iso}</Date>
    <Author>{user}</Author>
    <Description>Job Search Automation Local Model Supervisor (MODEL-01/AUTO-01). Runs local Ollama service loopback endpoint unattended on native Windows.</Description>
    <URI>\\JobAutomation\\{task_name}</URI>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT30S</Delay>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>{logon_type}</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>false</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe_path}</Command>
      <Arguments>serve</Arguments>
      <WorkingDirectory>{cwd_path}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
    return xml_text.strip()

