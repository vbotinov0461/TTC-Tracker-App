COMMANDS
uvicorn myfile:app --host 127.0.0.1 --port 8000 --reload


--- WORKER MODULE ---
When adding buses to congested routes in accordance with the bus budget, 
the routes that get serviced with more buses are FCFS, meaning, the budget
can be entirely spent on the first congested route that is selected when
iterating through the list of congested routes. 

As an update, you can either evenly distribute the budget across all
congested routes or apply route priorities. 


