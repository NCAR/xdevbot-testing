import ruamel.yaml as yaml
import requests
import os
import sys
import json
import copy


def register_repo(line, original_config):
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

    return config


if __name__ == "__main__":

    config_file = "config.yaml"
    with open(config_file) as resp:
        original_config = yaml.safe_load(resp)

    with open(os.environ["GITHUB_EVENT_PATH"], "r") as f:
        event_payload = json.load(f)
    comment = event_payload["issue"]["body"]
    # comment = "Foo\n/add-repo repo:NCAR/integral campaign:analysis\n/add-repo repo:NCAR/test campaign:core\nbar"
    comment = comment.splitlines()
    config = copy.deepcopy(original_config)
    for line in comment:
        config = register_repo(line, config)

    if config != original_config:
        with open(config_file, "w") as file_obj:
            yaml.round_trip_dump(config, file_obj, indent=2, block_seq_indent=2)
