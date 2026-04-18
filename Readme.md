- a software package to receive data from different sources and write them in csv files
- the software will run on a VPS server
- for now we used s flask environment so that my VPS has a live endpoint, for example http://<your-vps-ip>:8080/decode; as a n example you can see example/OMB_ArctSUM2025-PHP_EndpointToGeojson.txt
- I would like to develop this software package step by step. We are adding an observation or access point and make an operational setup possible on the VPS server.
- In parallel we are developing an html/java/css based website that visualizes the generated csv files; Here the data points of the last 30-days should be shown. By clickling on the data the csv file will be visualized in a subfigure with plotly to allow the user to explore the data in more detail; This needs to be adapted for the different data formats and observation; all this will be done also step-by-step by adding one after the other. 


