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
        <h2>Private Zone | Forbidden Area</h2>
        <?php
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            $enteredUsername = $_POST["username"];
            $enteredPassword = $_POST["password"];

            $usernames = "Sha";
            $passwords = "Dead";

            $userIndex = array_search($enteredUsername, $usernames);

            if ($userIndex !== false && $passwords[$userIndex] == $enteredPassword) {
                echo "<p>Login successful!</p>";
                 echo '<meta http-equiv="refresh" content="3; URL="/nopanels.php">';
            } else {
                echo "<p>Invalid username or password.</p>";
            }
        }
        ?>
        <form action="" method="post">
            <input class="input-field" type="text" name="username" placeholder="Username" required>
            <input class="input-field" type="password" name="password" placeholder="Password" required>
            <button class="submit-button" type="submit">Login</button>
        </form>
    </div>
</body>
</html>
