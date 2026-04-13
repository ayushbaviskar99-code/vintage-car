int total_amount(int price_per_ticket, int people_count) {
    if (people_count < 1) {
        return 0;
    }
    return price_per_ticket * people_count;
}
