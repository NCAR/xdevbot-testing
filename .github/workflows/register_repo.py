import yaml
import requests
import os
import sys
import json

if __name__ == "__main__":
    with open(os.environ["GITHUB_EVENT_PATH"], "r") as f:
        event_payload = json.load(f)
    comment = event_payload["issue"]["body"]
    if comment.startswith("/add-repo"):
        config_file = "config.yaml"
        with open(config_file) as resp:
            config = yaml.safe_load(resp)
        parsed_info = comment.split("/add-repo")[-1].strip().split()
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
            with open(config_file, "w") as file_obj:
                yaml.dump(config, file_obj, indent=4)

        else:
            print(f"{info['repo']} is registered already.")

    else:
        sys.exit(1)

