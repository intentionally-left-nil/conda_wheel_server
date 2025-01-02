setup:
	conda env $(shell [ -d ./env ] && echo update || echo create) -p ./env -f environment.yml

dev:
	conda run --live-stream -p ./env fastapi dev main.py

image:
	docker build -t conda_wheel_server:latest .

run_image: image
	mkdir -p repodata
	docker run -it -p 8000:8000 -v ./repodata:/repodata -e REPO_PASSWORD=password conda_wheel_server:latest
