FROM continuumio/miniconda3

ENV REPO_USERNAME=admin
ENV REPO_PASSWORD=password
ENV REPO_PATH=/repodata


WORKDIR /app
COPY environment.yml .
RUN conda env create -p ./env -f environment.yml
# Ensure /repodata is a directory for volume mounting
RUN mkdir /repodata
COPY main.py .
COPY metapackagestub-1.0-0.tar.bz2 .
EXPOSE 8000

# Run FastAPI
CMD ["conda", "run", "--no-capture-output", "-p", "./env", "fastapi", "run", "main.py"]
