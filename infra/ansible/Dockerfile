FROM python:3.12-slim

# Install Ansible and dependencies
RUN pip install --no-cache-dir \
    ansible-core \
    docker \
    && rm -rf /root/.cache

# Create working directory
WORKDIR /ansible

# Default command
ENTRYPOINT ["ansible-playbook"]
