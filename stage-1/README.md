Name: Oluwatofunmi Akinola
Slack Username: Oluwatofunmi Akinola
Project Description: 
	Deploying a web server managing a GitHub repository.
		* Setting up and managing Github workflow
		* Deploying and configuring a live NGINX server
		* Serve a custom page accessible on the internet
		
		## STEPS TO ACHIEVE 
			- Install nginx using apt ```sudo apt install nginx```
			- Enable the NGINX service ```sudo systemctl enable nginx ```
			- Start the nginx server ```sudo systemctl start nginx```
			- Run the nginx server ```nginx```
			- Run ```nginx -V``` to see the config path
			- Open the config path - And get the other configs included till you find where the server directive is hoisted.
				This will usually be in the /etc/nginx/sites-enabled/default file
			- update the port on the server directive to listen on the port you want and the root to server from the dir you expect
			- reload the NGINX server, using ```nginx -s reload``` and see your page live 
Server IP/domain: 168.231.116.189