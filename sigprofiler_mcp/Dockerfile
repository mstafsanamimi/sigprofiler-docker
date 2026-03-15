FROM sigprofiler-cpu
WORKDIR /srv
COPY requirements.txt server.py ./
RUN pip install --no-cache-dir -r requirements.txt
ENTRYPOINT ["python", "/srv/server.py"]
