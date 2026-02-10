FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    rsync \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Ansible
RUN pip install --no-cache-dir \
    ansible-core \
    && rm -rf /root/.cache

# Set up working directory
WORKDIR /ansible

# Copy ansible config
COPY ansible.cfg /etc/ansible/ansible.cfg

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ansible", "--version"]
