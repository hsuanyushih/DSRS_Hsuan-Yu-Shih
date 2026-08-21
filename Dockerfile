# Yours. Add whatever your pipeline needs.
#
#   docker build -f Dockerfile.base -t curator-base .
#   docker build -t curator-submission .
#   docker run --rm -v "$PWD/output:/app/output" -v "$PWD/.cache:/app/.cache" \
#     curator-submission --user-agent "FirstName LastName netid@illinois.edu"
#
# Keep the ENTRYPOINT below. We invoke the image directly, and overriding it will fail
# at grading time.

FROM curator-base

USER root
# System packages, if you need any. Most submissions will not.
# RUN apt-get update && apt-get install -y --no-install-recommends <pkg> \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements-extra.txt /app/requirements-extra.txt
RUN pip install --no-cache-dir -r /app/requirements-extra.txt

COPY --chown=runner:runner main.py /app/main.py
COPY --chown=runner:runner agents/ /app/agents/

USER runner

ENTRYPOINT ["python", "/app/main.py"]
CMD ["--help"]
