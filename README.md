8. Summary of Workflow

Deployment: You deploy the container using docker-compose up -d.

Access: You navigate to https://send.yourdomain.com.

Sending:

User A drags a 5GB .zip file into the "Send" box.

The file streams to the /app/data volume.

Server returns code: 9X2-B1L.

Sharing: User A texts the code 9X2-B1L to User B.

Receiving:

User B goes to the site, enters 9X2-B1L.

Server validates and immediately streams the 5GB file to User B.

(Optional) The file is auto-deleted from the server to free up space.
