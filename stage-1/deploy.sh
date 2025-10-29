#!/bin/bash

echo "Running shell: $BASH_VERSION"
set -euo pipefail


cleanup() {
  echo "🧹 Running cleanup..."
  # Stop running containers if needed
  if [[ -n "${ssh_ip:-}" && -n "${ssh_username:-}" && -n "${ssh_key_path:-}" ]]; then
   # perform ssh cleanup
    ssh -i "$ssh_key_path" "$ssh_username@$ssh_ip" "docker ps -q --filter 'name=my-app' | xargs -r docker stop"
    # Optionally remove old containers and images
    ssh -i "$ssh_key_path" "$ssh_username@$ssh_ip" "docker container prune -f && docker image prune -f"
   fi
  echo "Cleanup complete."
}

if [[ "${1:-}" == "--cleanup" ]]; then
  echo "⚙️ Cleanup mode activated..."
  cleanup
  exit 0
fi


LOG_FILE="deploy_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'echo "An error occurred on line $LINENO. Check $LOG_FILE for details." >&2' ERR


cleanup() {
  echo "🧹 Running cleanup..."
  # Stop running containers if needed
  ssh -i "$ssh_key_path" "$ssh_username@$ssh_ip" "docker ps -q --filter 'name=my-app' | xargs -r docker stop"

  # Optionally remove old containers and images
  ssh -i "$ssh_key_path" "$ssh_username@$ssh_ip" "docker container prune -f && docker image prune -f"

  echo "Cleanup complete."
}
trap cleanup EXIT


function prompt_nonempty() {
  local prompt_message=$1
  local varname=$2
  local input=""

  while [[ -z "$input" ]]; do
    read -p "$prompt_message" input

    if [[ -z "$input" ]]; then
      echo "Input cannot be empty. Please try again."
    fi
  done
  eval $varname="'$input'"


  # If input is a git URL, check it starts with https
  if [[ "$varname" == "git_repo_url" ]]; then
    while [[ "${input:0:5}" != "https" ]]; do
      echo "Please provide a valid HTTPS Git repository URL."
      read -p "$prompt_message" input
    done
  fi


  # If input is a port, validate it's a number
  if [[ "$varname" == "port" ]]; then
    while ! [[ "$input" =~ ^[0-9]+$ ]]; do
      echo "Port must be a number. Please try again."
      read -p "$prompt_message" input
    done
  fi
}

# Collect Parameters from User Input
prompt_nonempty "Enter your Git Repo URL: " git_repo_url

read -sp "Enter your Git PAT token: " git_PAT

echo

while [[ -z "$git_PAT" ]];
do
        echo "PAT token cannot be empty. Please try again."
        read -sp "Enter your Git PAT token: " git_PAT
        echo
done

read -p "Enter your branch name: " git_branch_name
git_branch_name=${git_branch_name:-main}
echo "Branch name is: $git_branch_name"

echo "-------------------------------------------"

echo "Please provide your SSH details in the order specified"
prompt_nonempty "Enter your SSH username: " ssh_username
prompt_nonempty "Enter your SSH IP address: " ssh_ip
prompt_nonempty "Enter your SSH key path: " ssh_key_path
prompt_nonempty "Enter the port where your application runs on: " port

# 2. Clone the Repository
echo "Please make sure you're running this script in the right directory"
echo "You can kill the script and rerun in the right directory, you have 5 seconds"

sleep 3

echo "Cloning your repository now"
clone_url="${git_repo_url:0:8}${git_PAT}@${git_repo_url:8}"
echo "cloning your url -> $clone_url"
# echo "${clone_url:0:${#clone_url}-4}"
echo "${clone_url:0:-4}"


# verfiy that repo doesn't already exit
IFS="/" read -ra new_url <<< "${clone_url:0:-4}"

cwd=$(pwd)
idx=$(( ${#new_url[@]} - 1 ))
repo_name="${new_url[$idx]}"
echo $repo_name
echo "WORKING URL -> $cwd/$repo_name"

if [[ -n "$repo_name" && -d "$cwd/$repo_name" && -d "$cwd/$repo_name/.git" ]]; then
  git fetch && git pull
  git checkout $git_branch_name
else
  git clone $clone_url
  cd $repo_name
fi

if [[ -f docker-compose.yml || -f Dockerfile ]]; then
    echo "Success"
  else
    echo "Failure"
fi


ping -c 2 "$ssh_ip" > /dev/null
ssh -i "$ssh_key_path" "$ssh_username@$ssh_ip" <<EOF
sudo apt update -y
# Add Docker's official GPG key:
sudo apt-get update -y
sudo apt install -y jq
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo systemctl enable --now docker
sudo systemctl enable --now nginx

sudo systemctl start docker
sudo usermod -aG docker "$USER"
docker --version 
nginx -v
EOF

rsync -avz -e "ssh -i $ssh_key_path" --exclude='.git' $cwd/$repo_name "$ssh_username@$ssh_ip:~/"

ssh -i "$ssh_key_path" "$ssh_username@$ssh_ip" <<EOF
cd $repo_name

if [ -f docker-compose.yml ]; then
    docker compose up -d --build
else
    docker build -t my-app .
    docker run -d -p $port:$port my-app
fi

CONTAINER_NAME=$(docker ps --latest --format '{{.Names}}')
docker logs --tail 15 "$CONTAINER_NAME"

HEALTH_STATUS=$(docker inspect --format='{{json .State.Health}}' "$CONTAINER_NAME" 2>/dev/null)
if [ -n "$HEALTH_STATUS" ]; then
  echo
  echo "🩺 Container health details:"
  echo "$HEALTH_STATUS" | jq .
else
  echo
  echo "No HEALTHCHECK defined in Dockerfile."
fi
EOF


ssh -i "$ssh_key_path" "$ssh_username@$ssh_ip" <<'REMOTE'
echo "Configuring NGINX reverse proxy..."

NGINX_CONF="/etc/nginx/sites-available/my-app"

# Create new NGINX config dynamically
sudo bash -c "cat > $NGINX_CONF" <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:$port;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
REMOTE

# Enable the site
sudo ln -sf $NGINX_CONF /etc/nginx/sites-enabled/my-app

# Test and reload
sudo nginx -t && sudo systemctl reload nginx

if [ $? -eq 0 ]; then
    echo "NGINX reverse proxy configured successfully"
else
    echo "NGINX configuration failed"
    exit 1
fi
