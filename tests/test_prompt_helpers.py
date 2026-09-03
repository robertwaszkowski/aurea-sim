import pytest
from aureasim.ai_generator import prompt_task_name

def test_prompt_task_name_prefers_clean_name():
    task = {
        "task_id": "Activity_1",
        "task_name": "Sign agreement [director]",
        "clean_task_name": "Sign agreement",
    }
    assert prompt_task_name(task) == "Sign agreement"

def test_prompt_task_name_fallback_to_task_name():
    task = {
        "task_id": "Activity_1",
        "task_name": "Sign agreement [director]",
        "clean_task_name": "",
    }
    assert prompt_task_name(task) == "Sign agreement [director]"

def test_prompt_task_name_fallback_to_task_id():
    task = {
        "task_id": "Activity_1",
        "task_name": "",
        "clean_task_name": "",
    }
    assert prompt_task_name(task) == "Activity_1"

def test_prompt_task_name_fallback_unnamed():
    task = {}
    assert prompt_task_name(task) == "Unnamed task"
