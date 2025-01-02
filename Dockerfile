FROM continuumio/miniconda3

ENV REPO_USERNAME=admin
ENV REPO_PASSWORD=password
ENV REPO_PATH=/repodata


WORKDIR /app
COPY environment.yml .
RUN conda env create -p ./env -f environment.yml
COPY main.py .
EXPOSE 8000

# Run FastAPI
CMD ["conda", "run", "--no-capture-output", "-p", "./env", "fastapi", "run", "main.py"]
