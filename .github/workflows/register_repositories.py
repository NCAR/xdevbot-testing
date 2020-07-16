import asyncio
from typing import SupportsRound
import aiohttp
import logging
import os

import ruamel.yaml as yaml
import requests
import sys
import json
import copy
from datetime import datetime

logging.basicConfig(level=logging.INFO)

API_BASE_URL = "https://api.github.com"

XDEVBOT_MAIN_ENDPOINT = "http://xdevbot.herokuapp.com/gh/testing"


def register_repo(line, original_config, repos=[]):
    config = copy.deepcopy(original_config)
    if line.startswith("/add-repo"):
        parsed_info = line.split("/add-repo")[-1].strip().split()
        info = {}
        for item in parsed_info:
            x = item.strip().split(":")
            info[x[0]] = x[1]

        info["repo_url"] = f"https://github.com/{info['repo']}"
        request = requests.get(info["repo_url"])
        if request.status_code != 200:
            raise Exception(
                f'{info["repo_url"]} does not appear to be a git repository.'
            )

        if info["repo"] not in set(config[info["campaign"]]["repos"]):
            config[info["campaign"]]["repos"].append(info["repo"])
            repos.append(info["repo"])

    return config


def configure(config_file="config.yaml"):
    repos = []
    with open(config_file) as resp:
        original_config = yaml.safe_load(resp)

    # with open(os.environ["GITHUB_EVENT_PATH"], "r") as f:
    #     event_payload = json.load(f)
    # comment = event_payload["issue"]["body"]
    comment = "Foo\n/add-repo repo:NCAR/integral campaign:analysis\n/add-repo repo:NCAR/test campaign:core\nbar\n/add-repo repo:NCAR/xdevbot-testing campaign:core"
    comment = comment.splitlines()
    config = copy.deepcopy(original_config)
    for line in comment:
        config = register_repo(line, config, repos)
    return config, original_config, set(repos)


async def install_repo_webhook(
    repo,
    hooks_info={},
    username=os.environ.get("GH_USERNAME", ""),
    token=os.environ.get("GH_TOKEN", ""),
):

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
        "User-Agent": username,
    }

    url = f"{API_BASE_URL}/repos/{repo}/hooks"

    async with aiohttp.ClientSession(headers=headers) as client:

        logging.info("Retrieving repository metadata.")
        async with client.get(url) as response:
            hooks = await response.json()
            if response.status == 200:
                potl_hooks = []
                for hook in hooks:
                    if (
                        set(hook["events"]) == {"issues", "pull_request"}
                        and hook["config"]["url"] == XDEVBOT_MAIN_ENDPOINT
                        and hook["config"]["content_type"] == "json"
                        and hook["active"]
                    ):
                        potl_hooks.append(hook)

                if len(potl_hooks) == 0:
                    logging.info("Creating repository webhook.")
                    request = dict(
                        name="web",
                        events=["issues", "pull_request"],
                        config=dict(url=XDEVBOT_MAIN_ENDPOINT, content_type="json"),
                    )
                    async with client.post(url, json=request) as response:
                        main_hook = await response.json()
                        if response.status != 201:
                            logging.error("Failed to create repository webhook.")

                elif len(potl_hooks) == 1:
                    logging.info("Existing repository webhook found.")
                    main_hook = potl_hooks[0]

                else:
                    timestamps = [
                        datetime.strptime(hook["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
                        for hook in potl_hooks
                    ]
                    newest_timestamp, i_hook = max(
                        (t, i) for (i, t) in enumerate(timestamps)
                    )[1]
                    logging.info(
                        f"Found {len(potl_hooks)} potential webhooks on the repository, "
                        f"choosing most recent webhook at {newest_timestamp}."
                    )
                    main_hook = potl_hooks[i_hook]

                hooks_info[repo] = main_hook

            else:
                logging.error("Could not retrieve repository metadata.")


if __name__ == "__main__":

    config_file = "config.yaml"
    new_config, old_config, repos = configure(config_file)
    if new_config != old_config:
        with open(config_file, "w") as file_obj:
            yaml.round_trip_dump(new_config, file_obj, indent=2, block_seq_indent=2)
    hooks_info = {}
    loop = asyncio.get_event_loop()
    # repos = {'NCAR/xdevbot-testing', 'NCAR/jupyterlab-pbs', 'NCAR/PyCECT'}
    tasks = [loop.create_task(install_repo_webhook(repo, hooks_info)) for repo in repos]
    loop.run_until_complete(asyncio.gather(*tasks))
    successes = set(hooks_info.keys())
    failures = repos - successes

    with open("hooks_log.txt", "w") as f:
        if successes:
            print("\n**Webhook was successfully installed on:**\n", file=f)
            for repo in successes:
                print(f"- {repo}", file=f)

        if failures:
            print("\n**Unable to install the webhook on:**\n", file=f)
            for repo in failures:
                print(f"- {repo}", file=f)
