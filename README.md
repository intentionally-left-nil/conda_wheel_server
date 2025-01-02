# Conda Wheel server

Simple FastAPI server used to host multiple repodata.json files. The generated repodata must use the URL /wheel?base_64_encoded_url which will then be redirected to PyPI

## Getting started
`make setup` followed by `make run` for local development

To deploy: `make run_image`
Make sure to set the REPO_PASSWORD environment variable :)

## Conda routes
/repo/channel_name/architecture/repodata.json
Simple GET route for the repodata

/repo/channel_name/architecture/file.whl
Does a lookup based off the build string for the wheel to find the appropriate URL

## Admin routes

### Create or upload a new channel
POST /repo/{channel_name}/{arch}/repodata.json
Uploads a repodata. Make sure to use basic auth. Example cURL command:
```sh
curl -X POST "localhost:8000/repo/my_cool_channel/noarch/repodata.json" -u admin:password -F "file=@/path/to/repodata.json"
```

### Create or update the wheel_index
The /wheels route expects a JSON file in the following format
```json
{
  "build_num_uuid": "https://files.pythonhosted.org/...",
  "build_num_uuid2" "..."
}
```
where the wheel "build number" corresponds to the actual location of the wheel file. Again, make sure to use basic auth
Example cURL command:
```sh
curl -X POST "localhost:8000/repo/wheels" -u admin:password -F "file=@/path/to/wheel_index.json"
```