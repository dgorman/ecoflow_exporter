import os
import paramiko
from scp import SCPClient
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv("/Users/home/dgorman/Dev/.env")

# Configuration
synology_ip = "192.168.1.4"
synology_user = "admin"
synology_password = os.getenv("SYN_PASSWORD")
nuc_ip = "192.168.2.22"
nuc_user = "admin"
nuc_password = os.getenv("NUC_PASSWORD")
container_export_path = "/tmp/docker_exports"
nuc_import_path = "/home/ubuntu/docker_imports"
private_key_path = "/root/.ssh/id_ed25519"
private_key_passphrase = os.getenv("PRIVATE_KEY_PASSPHRASE")

def create_ssh_client(hostname, username, password, key_path, key_passphrase):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    # Load the private key with passphrase
    private_key = paramiko.RSAKey.from_private_key_file(key_path, password=key_passphrase)
    
    client.connect(hostname, username=username, pkey=private_key)
    return client

# Step 1: Connect to Synology NAS and export containers
def export_containers_from_synology():
    print("Step 1: Exporting containers from Synology NAS")
    ssh_client = create_ssh_client(synology_ip, synology_user, synology_password, private_key_path, private_key_passphrase)

    # Ensure the export directory exists
    print(f"Ensuring export directory exists on Synology ({synology_ip}): {container_export_path}")
    ssh_client.exec_command(f"mkdir -p {container_export_path}")

    # List all running containers
    list_containers_command = "sudo -S docker ps -q"
    print(f"Executing on Synology ({synology_ip}): {list_containers_command}")
    stdin, stdout, stderr = ssh_client.exec_command(list_containers_command)
    stdin.write(synology_password + "\n")
    stdin.flush()
    container_ids = stdout.read().decode().split()

    if not container_ids:
        print("No running containers found on Synology NAS.")
        ssh_client.close()
        return

    # Export each container
    for container_id in container_ids:
        export_command = f"sudo -S docker export -o {container_export_path}/{container_id}.tar {container_id}"
        print(f"Executing on Synology ({synology_ip}): {export_command}")
        stdin, stdout, stderr = ssh_client.exec_command(export_command)
        stdin.write(synology_password + "\n")
        stdin.flush()
        stdout.channel.recv_exit_status()  # Wait for command to complete

    ssh_client.close()

# Step 2: Transfer the tar files to the Intel NUC
def transfer_files_to_nuc():
    print("Step 2: Transferring tar files to Intel NUC")
    ssh_client = create_ssh_client(synology_ip, synology_user, synology_password, private_key_path, private_key_passphrase)
    scp_client = SCPClient(ssh_client.get_transport())

    # List tar files to ensure they exist
    list_files_command = f"ls {container_export_path}/*.tar"
    print(f"Executing on Synology ({synology_ip}): {list_files_command}")
    stdin, stdout, stderr = ssh_client.exec_command(list_files_command)
    tar_files = stdout.read().decode().split()

    if not tar_files:
        print("No tar files found in the export directory on Synology NAS.")
        ssh_client.close()
        return

    # Transfer tar files to local machine
    for tar_file in tar_files:
        print(f"Transferring {tar_file} from Synology to local machine")
        scp_client.get(tar_file, local_path=nuc_import_path)

    scp_client.close()
    ssh_client.close()

    # Transfer tar files from local machine to Intel NUC
    ssh_client = create_ssh_client(nuc_ip, nuc_user, nuc_password, private_key_path, private_key_passphrase)
    scp_client = SCPClient(ssh_client.get_transport())
    for tar_file in tar_files:
        local_tar_file = os.path.join(nuc_import_path, os.path.basename(tar_file))
        print(f"Transferring {local_tar_file} from local machine to Intel NUC ({nuc_ip})")
        scp_client.put(local_tar_file, remote_path=nuc_import_path)

    scp_client.close()
    ssh_client.close()

# Step 3: Import the containers on the Intel NUC
def import_containers_to_nuc():
    print("Step 3: Importing containers to Intel NUC")
    ssh_client = create_ssh_client(nuc_ip, nuc_user, nuc_password, private_key_path, private_key_passphrase)
    stdin, stdout, stderr = ssh_client.exec_command(f"ls {nuc_import_path}")
    tar_files = stdout.read().decode().split()

    for tar_file in tar_files:
        import_command = f"docker load -i {nuc_import_path}/{tar_file}"
        print(f"Executing on NUC ({nuc_ip}): {import_command}")
        ssh_client.exec_command(import_command)
        stdout.channel.recv_exit_status()  # Wait for command to complete

        stdin, stdout, stderr = ssh_client.exec_command("docker images -q | head -n 1")
        image_id = stdout.read().decode().strip()
        start_command = f"docker run -d {image_id}"
        print(f"Executing on NUC ({nuc_ip}): {start_command}")
        ssh_client.exec_command(start_command)
        stdout.channel.recv_exit_status()  # Wait for command to complete

    ssh_client.close()

if __name__ == "__main__":
    export_containers_from_synology()
    transfer_files_to_nuc()
    import_containers_to_nuc()