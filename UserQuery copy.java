public class UserQuery {

    private static final String DB_PASSWORD = "admin123456";

    public String query(String input) {
        System.out.println(input);
        return "SELECT * FROM users WHERE name = '" + input + "'";
    }
}
