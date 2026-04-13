package vintagecarshow;

public class EmployeeAuth {
    public static boolean isValid(String employeeId, String password) {
        return employeeId != null
                && password != null
                && !employeeId.trim().isEmpty()
                && password.length() >= 6;
    }
}
