# Environment installation

An Ansible playbook and roles is available for a complete environment installation on a real Cloud platform.

For environment installation you need 7 virtual machines with the following specs:

Agent: 4 VCPU/16 GB RAM/40GB storage

Injector 1&2: 4VCPU/4GB RAM/40 GB storage

Kubernetes 1&2&3&4: 8VCPU/16 GB RAM/40 GB storage

This installation procedure has been only tested on: Debian 9

This installation procedure does not create the virtual machines but it is planned. 

## Environment and installation constraints

Each virtual must have direct internet access either through a dedicated floating IP or through a NAT Gateway.

The communication must not be filtered between virtual machine. On Openstack you can create a unique security group for all virtual machine which allows full inbound communication for the security group itself only. As you will need to access services on the virtual machine you can add your own IP address in this security group.

This installation procedure is so not secure and must be performed by a competent person with good knowledge of security implication. This must not be installed in sensible aera where environment is strategic. We cannot and will not be liable for any loss or damage arising from this installation procedure. 

## Installation steps

After creating the virtual machines you will have:

- An ssh private key

- A private network adresse

- 7 virtual machines with direct internet access and a dedicated IP address for each virtual machine on the private network

  

As the ssh user depends on the Cloud provided we will used the ssh user : cloud as an example.

To start the environment installation performs the following steps:

1- Connect with ssh on the virtual machine agent1 with the user cloud

2- Copy the ssh private key under the ssh user (cloud) of the virtual machine agent1 in /home/cloud/.ssh/id_rsa with right 600

3- git clone our repository and go under the directory HSLinUCB

4- Edit the file host.yaml and update the following information

```
openstack_network: 192.168.0.0/24
```

Place here your cloud private network address in CIDR format.

```
ansible_host: 192.168.0.60 

ansible_user: cloud
```

Replace all ansible_host variable with the IP address of your virtual machines

Replace all ansible_user with the ssh user used to connect on the virtual machine

```
jupyterlab_account:
	- user:
			login: david
			password: davidpassword
```

Replace the variable login with your desired login for the JupyterLab interface

Do the same thing for the password

5- ansible installation

Executes the following command to install ansible:

```
# wget https://repo.anaconda.com/archive/Anaconda3-2020.07-Linux-x86_64.sh

# chmod +x Anaconda3-2020.07-Linux-x86_64.sh

# bash ./Anaconda3-2020.07-Linux-x86_64.sh -b -p /home/cloud/anaconda

# /home/cloud/anaconda/bin/conda init

# source ~/.bashrc

# conda update -y conda

# conda create --name ansible python=3.7

# conda activate ansible

# pip install ansible==2.10.2
```

6- start installation

```
ansible-playbook -i hosts.yaml full_deployment.yml
```

Once the installation finished you can access the jupyterlabs interface on:

http://<agent1 internet address>::8000/hubagent/hub/login

The locust injector interface is available with a browser on the stress server on port 8089

kubectl command is available on every virtual machines
